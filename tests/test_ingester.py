"""
Tests for akasha.ingester — 知识摄入器。

LLM 调用通过 mock 替代，测试核心逻辑:
- ingest: JSON 解析、页面创建/合并、index/log 更新
- save_as_page: 页面生成和保存
- lint: 健康检查规则
"""

import json
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from akasha.config import Config
from akasha.ingester import Ingester, IngestResult, LintIssue


# ============================================================================
# Fixtures
# ============================================================================


@pytest.fixture
def wiki_vault(tmp_path: Path) -> Path:
    """创建带 wiki 结构的 vault。返回 vault 根目录（内容在 docs/ 下）。"""
    docs = tmp_path / "docs"

    # raw 目录 + 测试源文件
    raw_dir = docs / "raw" / "analysis"
    raw_dir.mkdir(parents=True)
    (raw_dir / "test-source.md").write_text(
        """\
---
tags: [agent, design-pattern]
title: Test Source
---

# Test Source

## Agent Loop

Agent Loop 是一种设计模式，通过 Think → Act → Observe 循环完成任务。

## MCP 协议

MCP 是 Model Context Protocol，用于 AI 工具调用。
""",
        encoding="utf-8",
    )

    # wiki 目录
    (docs / "wiki" / "concepts").mkdir(parents=True)
    (docs / "wiki" / "entities").mkdir(parents=True)
    (docs / "wiki" / "comparisons").mkdir(parents=True)
    (docs / "wiki" / "synthesis").mkdir(parents=True)

    # schema.md
    (docs / "schema.md").write_text("# Schema\n\n规则文件", encoding="utf-8")

    # index.md
    (docs / "index.md").write_text(
        """\
# 知识库目录

## 概念 (concepts/)

*暂无条目 — 执行 ingest 后自动生成。*

## 实体 (entities/)

*暂无条目 — 执行 ingest 后自动生成。*

## 对比 (comparisons/)

*暂无条目 — 执行 ingest 后自动生成。*

## 综合 (synthesis/)

*暂无条目 — 执行 save_as_page 后自动生成。*
""",
        encoding="utf-8",
    )

    # log.md
    (docs / "log.md").write_text("# 知识库日志\n\n---\n", encoding="utf-8")

    return tmp_path


@pytest.fixture
def wiki_config(wiki_vault: Path, tmp_path: Path) -> Config:
    return Config(
        vault_path=wiki_vault,
        chroma_dir=tmp_path / "chroma",
        llm_api_key="test-key",
        llm_base_url="http://localhost:8080/v1",
        llm_model="test-model",
    )


@pytest.fixture
def mock_llm():
    """Mock LLMClient。"""
    llm = AsyncMock()
    return llm


@pytest.fixture
def ingester(wiki_config: Config, mock_llm) -> Ingester:
    ing = Ingester.__new__(Ingester)
    ing.config = wiki_config
    ing.llm = mock_llm
    return ing


# ============================================================================
# _parse_json_response
# ============================================================================


class TestParseJsonResponse:
    def test_plain_json(self):
        text = '{"concepts": ["A"], "pages": []}'
        result = Ingester._parse_json_response(text)
        assert result == {"concepts": ["A"], "pages": []}

    def test_json_in_code_block(self):
        text = '```json\n{"concepts": ["B"], "pages": []}\n```'
        result = Ingester._parse_json_response(text)
        assert result == {"concepts": ["B"], "pages": []}

    def test_json_with_surrounding_text(self):
        text = 'Here is the result:\n{"concepts": ["C"], "pages": []}\nDone.'
        result = Ingester._parse_json_response(text)
        assert result == {"concepts": ["C"], "pages": []}

    def test_invalid_json(self):
        result = Ingester._parse_json_response("not json at all")
        assert result is None

    def test_empty_string(self):
        result = Ingester._parse_json_response("")
        assert result is None


# ============================================================================
# ingest
# ============================================================================


@pytest.mark.asyncio
class TestIngest:
    async def test_ingest_creates_pages(self, ingester: Ingester, wiki_vault: Path):
        """ingest 应创建新的 wiki 页面。"""
        # Mock LLM 返回
        llm_response = json.dumps(
            {
                "concepts": ["Agent Loop", "MCP"],
                "pages": [
                    {
                        "path": "wiki/concepts/agent-loop.md",
                        "content": (
                            "---\ntitle: Agent Loop\ntags: [agent]\n"
                            "sources:\n  - raw/analysis/test-source.md\n"
                            "related:\n  - wiki/concepts/mcp.md\n"
                            "created: 2026-04-14\nupdated: 2026-04-14\n"
                            "status: seedling\n---\n\n"
                            "# Agent Loop\n\nThink → Act → Observe 循环。\n"
                        ),
                    },
                    {
                        "path": "wiki/concepts/mcp.md",
                        "content": (
                            "---\ntitle: MCP\ntags: [mcp, protocol]\n"
                            "sources:\n  - raw/analysis/test-source.md\n"
                            "related:\n  - wiki/concepts/agent-loop.md\n"
                            "created: 2026-04-14\nupdated: 2026-04-14\n"
                            "status: seedling\n---\n\n"
                            "# MCP\n\nModel Context Protocol。\n"
                        ),
                    },
                ],
            }
        )
        ingester.llm.chat.return_value = llm_response

        result = await ingester.ingest("raw/analysis/test-source.md")

        assert isinstance(result, IngestResult)
        assert result.source_file == "raw/analysis/test-source.md"
        assert "Agent Loop" in result.concepts_extracted
        assert "MCP" in result.concepts_extracted
        assert len(result.pages_created) == 2
        assert "wiki/concepts/agent-loop.md" in result.pages_created

        # 验证文件已创建
        assert (wiki_vault / "docs/wiki/concepts/agent-loop.md").exists()
        assert (wiki_vault / "docs/wiki/concepts/mcp.md").exists()

    async def test_ingest_updates_existing_page(
        self, ingester: Ingester, wiki_vault: Path
    ):
        """ingest 应合并到已有页面。"""
        # 先创建一个已有页面
        existing_page = wiki_vault / "docs/wiki/concepts/agent-loop.md"
        existing_page.write_text("# Agent Loop\n\n旧内容。\n", encoding="utf-8")

        # Mock: extract 返回要更新的页面
        extract_response = json.dumps(
            {
                "concepts": ["Agent Loop"],
                "pages": [
                    {
                        "path": "wiki/concepts/agent-loop.md",
                        "content": "新信息内容",
                    },
                ],
            }
        )
        # Mock: merge 返回合并结果
        merge_result = "# Agent Loop\n\n旧内容。\n\n## 新增\n\n新信息。\n"

        ingester.llm.chat.side_effect = [extract_response, merge_result]

        result = await ingester.ingest("raw/analysis/test-source.md")

        assert len(result.pages_updated) == 1
        assert "wiki/concepts/agent-loop.md" in result.pages_updated

        # 验证文件内容被更新
        content = existing_page.read_text(encoding="utf-8")
        assert "新增" in content

    async def test_ingest_updates_index(self, ingester: Ingester, wiki_vault: Path):
        """ingest 后 index.md 应更新。"""
        llm_response = json.dumps(
            {
                "concepts": ["Agent Loop"],
                "pages": [
                    {
                        "path": "wiki/concepts/agent-loop.md",
                        "content": "---\ntitle: Agent Loop\n---\n# Agent Loop\n",
                    },
                ],
            }
        )
        ingester.llm.chat.return_value = llm_response

        await ingester.ingest("raw/analysis/test-source.md")

        index = (wiki_vault / "docs/index.md").read_text(encoding="utf-8")
        assert "agent-loop" in index

    async def test_ingest_updates_log(self, ingester: Ingester, wiki_vault: Path):
        """ingest 后 log.md 应追加。"""
        llm_response = json.dumps(
            {
                "concepts": ["Agent Loop"],
                "pages": [
                    {
                        "path": "wiki/concepts/agent-loop.md",
                        "content": "# Agent Loop\n",
                    },
                ],
            }
        )
        ingester.llm.chat.return_value = llm_response

        await ingester.ingest("raw/analysis/test-source.md")

        log = (wiki_vault / "docs/log.md").read_text(encoding="utf-8")
        assert "ingest" in log
        assert "test-source.md" in log

    async def test_ingest_nonexistent_file(self, ingester: Ingester):
        """不存在的文件应抛出 FileNotFoundError。"""
        with pytest.raises(FileNotFoundError):
            await ingester.ingest("raw/nonexistent.md")

    async def test_ingest_bad_llm_response(self, ingester: Ingester, wiki_vault: Path):
        """LLM 返回无效 JSON 应不崩溃。"""
        ingester.llm.chat.return_value = "这不是 JSON"

        result = await ingester.ingest("raw/analysis/test-source.md")
        assert result.source_file == "raw/analysis/test-source.md"
        assert len(result.pages_created) == 0
        assert len(result.concepts_extracted) == 0


# ============================================================================
# save_as_page
# ============================================================================


@pytest.mark.asyncio
class TestSaveAsPage:
    async def test_save_creates_page(self, ingester: Ingester, wiki_vault: Path):
        """save_as_page 应创建 wiki 页面。"""
        ingester.llm.chat.return_value = (
            "---\ntitle: Agent 设计模式总结\ntags: [agent]\n"
            "sources: []\nrelated: []\n"
            "created: 2026-04-14\nupdated: 2026-04-14\n"
            "status: seedling\n---\n\n# Agent 设计模式总结\n\n总结内容。\n"
        )

        path = await ingester.save_as_page(
            title="Agent 设计模式总结",
            content="这是一段关于 Agent 设计模式的总结...",
            category="synthesis",
        )

        assert "wiki/synthesis/" in path
        assert (wiki_vault / "docs" / path).exists()

    async def test_save_updates_index_and_log(
        self, ingester: Ingester, wiki_vault: Path
    ):
        ingester.llm.chat.return_value = "---\ntitle: Test\n---\n# Test\n"

        await ingester.save_as_page("Test Page", "Content", "synthesis")

        index = (wiki_vault / "docs/index.md").read_text(encoding="utf-8")
        log = (wiki_vault / "docs/log.md").read_text(encoding="utf-8")
        assert "save_as_page" in log or "对话生成" in log


# ============================================================================
# lint
# ============================================================================


class TestLint:
    def test_lint_empty_wiki(self, ingester: Ingester):
        """空 wiki 应无问题。"""
        issues = ingester.lint()
        assert issues == []

    def test_lint_missing_frontmatter(self, ingester: Ingester, wiki_vault: Path):
        """缺少 frontmatter 应报告。"""
        page = wiki_vault / "docs/wiki/concepts/test.md"
        page.write_text(
            "# Test\n\nNo frontmatter here. This is a page without YAML header that should be flagged.",
            encoding="utf-8",
        )

        issues = ingester.lint()
        types = [i.type for i in issues]
        assert "missing_frontmatter" in types

    def test_lint_orphan_page(self, ingester: Ingester, wiki_vault: Path):
        """没有被引用的页面应报告 orphan。"""
        page = wiki_vault / "docs/wiki/concepts/lonely.md"
        page.write_text(
            "---\ntitle: Lonely\n---\n# Lonely\n\n没有其他页面引用我。这是一个孤立页面。",
            encoding="utf-8",
        )

        issues = ingester.lint()
        types = [i.type for i in issues]
        assert "orphan" in types

    def test_lint_few_links(self, ingester: Ingester, wiki_vault: Path):
        """引用过少应报告。"""
        page = wiki_vault / "docs/wiki/concepts/sparse.md"
        page.write_text(
            "---\ntitle: Sparse\n---\n# Sparse\n\n只有一个链接 [[other]]。这个页面引用太少了。",
            encoding="utf-8",
        )

        issues = ingester.lint()
        types = [i.type for i in issues]
        assert "few_links" in types

    def test_lint_healthy_page(self, ingester: Ingester, wiki_vault: Path):
        """健康页面不应有 missing_frontmatter 问题。"""
        # 创建两个互相引用的页面
        (wiki_vault / "docs/wiki/concepts/alpha.md").write_text(
            "---\ntitle: Alpha\n---\n# Alpha\n\n参见 [[beta]] 和 [[gamma]]。这是健康的 alpha 页面。",
            encoding="utf-8",
        )
        (wiki_vault / "docs/wiki/concepts/beta.md").write_text(
            "---\ntitle: Beta\n---\n# Beta\n\n参见 [[alpha]] 和 [[gamma]]。这是健康的 beta 页面。",
            encoding="utf-8",
        )
        (wiki_vault / "docs/wiki/concepts/gamma.md").write_text(
            "---\ntitle: Gamma\n---\n# Gamma\n\n参见 [[alpha]] 和 [[beta]]。这是健康的 gamma 页面。",
            encoding="utf-8",
        )

        issues = ingester.lint()
        # 不应有 missing_frontmatter 或 few_links
        for issue in issues:
            assert issue.type not in ("missing_frontmatter", "few_links")

    def test_lint_empty_page(self, ingester: Ingester, wiki_vault: Path):
        """空页面应报告。"""
        page = wiki_vault / "docs/wiki/concepts/empty.md"
        page.write_text("# E\n\nShort.", encoding="utf-8")

        issues = ingester.lint()
        types = [i.type for i in issues]
        assert "empty" in types
