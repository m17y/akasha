"""
测试知识编译器 — Phase 2。

覆盖:
- Compiler.lint（纯规则，不需要 LLM）
- Compiler.ingest（mock LLM）
- Compiler.save_as_page（mock LLM）
- Vault.lint / vault.ingest / vault.save_page 集成
"""

import os
import json
import pytest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

from akasha.vault import Vault
from akasha.compiler import Compiler, IngestResult, LintIssue
from akasha.storage.files import FileStore
from akasha.config import Config


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def vault(tmp_path: Path) -> Vault:
    """创建一个带测试数据的 Vault。"""
    vault_path = tmp_path / "vault"
    os.environ["AKASHA_VAULT_PATH"] = str(vault_path)
    os.environ["AKASHA_CHROMA_DIR"] = str(tmp_path / "chroma")
    os.environ["AKASHA_LLM_API_KEY"] = ""  # 默认无 LLM

    v = Vault(vault_path)
    v.init()

    docs = vault_path / "docs"
    note = docs / "raw" / "notes" / "test-article.md"
    note.write_text(
        """\
---
tags: [test, article]
title: 测试文章
---

# 测试文章

这是一篇测试文章，用来验证 ingest 功能。

## Agent Loop

Agent Loop 是一种设计模式。

## RAG

RAG 是检索增强生成。
""",
        encoding="utf-8",
    )

    return v


@pytest.fixture
def mock_llm():
    """创建一个 mock LLM 客户端。"""
    llm = MagicMock()
    llm.chat = AsyncMock()
    return llm


@pytest.fixture
def compiler(vault: Vault, mock_llm) -> Compiler:
    """创建一个使用 mock LLM 的 Compiler。"""
    return Compiler(vault.config, vault.files, mock_llm)


# ---------------------------------------------------------------------------
# Lint 测试（不需要 LLM）
# ---------------------------------------------------------------------------


class TestLint:
    def test_lint_empty_wiki(self, compiler: Compiler):
        """空 wiki 不应该有问题。"""
        issues = compiler.lint()
        assert issues == []

    def test_lint_missing_frontmatter(self, vault: Vault, compiler: Compiler):
        """检测缺失 frontmatter。"""
        vault.files.write_wiki(
            "wiki/concepts/no-frontmatter.md",
            "# No Frontmatter\n\nThis page has no frontmatter, which is enough content to pass the length check.",
        )
        issues = compiler.lint()
        types = [i.type for i in issues]
        assert "missing_frontmatter" in types

    def test_lint_empty_page(self, vault: Vault, compiler: Compiler):
        """检测空页面。"""
        vault.files.write_wiki("wiki/concepts/empty.md", "# Hi\n")
        issues = compiler.lint()
        types = [i.type for i in issues]
        assert "empty" in types

    def test_lint_orphan_page(self, vault: Vault, compiler: Compiler):
        """检测孤立页面。"""
        vault.files.write_wiki(
            "wiki/concepts/orphan.md",
            "---\ntitle: Orphan\ntags: [test]\n---\n\n# Orphan Page\n\nThis page is not referenced by any other page. It has enough content.\n",
        )
        issues = compiler.lint()
        types = [i.type for i in issues]
        assert "orphan" in types

    def test_lint_few_links(self, vault: Vault, compiler: Compiler):
        """检测引用过少。"""
        vault.files.write_wiki(
            "wiki/concepts/few-links.md",
            "---\ntitle: Few Links\ntags: [test]\n---\n\n# Few Links\n\nOnly one link: [[orphan]]. This page needs more references to other pages.\n",
        )
        issues = compiler.lint()
        types = [i.type for i in issues]
        assert "few_links" in types

    def test_vault_lint_integration(self, vault: Vault):
        """通过 Vault.lint() 调用。"""
        result = vault.lint()
        assert "通过" in result or "问题" in result


# ---------------------------------------------------------------------------
# Ingest 测试（mock LLM）
# ---------------------------------------------------------------------------


class TestIngest:
    @pytest.mark.asyncio(loop_scope="function")
    async def test_ingest_creates_pages(
        self, vault: Vault, compiler: Compiler, mock_llm
    ):
        """ingest 应该创建 wiki 页面。"""
        mock_llm.chat.return_value = json.dumps(
            {
                "concepts": ["Agent Loop", "RAG"],
                "pages": [
                    {
                        "path": "wiki/concepts/agent-loop.md",
                        "content": "---\ntitle: Agent Loop\ntags: [agent]\nsources: [raw/notes/test-article.md]\nrelated: []\ncreated: 2026-04-15\nupdated: 2026-04-15\nstatus: seedling\n---\n\n# Agent Loop\n\nAgent Loop 是一种设计模式。",
                    },
                    {
                        "path": "wiki/concepts/rag.md",
                        "content": "---\ntitle: RAG\ntags: [rag]\nsources: [raw/notes/test-article.md]\nrelated: [wiki/concepts/agent-loop.md]\ncreated: 2026-04-15\nupdated: 2026-04-15\nstatus: seedling\n---\n\n# RAG\n\n检索增强生成。",
                    },
                ],
            }
        )

        result = await compiler.ingest("raw/notes/test-article.md")

        assert result.source_file == "raw/notes/test-article.md"
        assert len(result.pages_created) == 2
        assert "wiki/concepts/agent-loop.md" in result.pages_created
        assert "Agent Loop" in result.concepts_extracted

        # 验证文件确实被创建了
        content = vault.files.read_raw("wiki/concepts/agent-loop.md")
        assert "Agent Loop" in content

    @pytest.mark.asyncio(loop_scope="function")
    async def test_ingest_merges_existing(
        self, vault: Vault, compiler: Compiler, mock_llm
    ):
        """ingest 已有页面时应该合并。"""
        # 先创建一个已有页面
        vault.files.write_wiki(
            "wiki/concepts/agent-loop.md",
            "---\ntitle: Agent Loop\n---\n\n# Agent Loop\n\n旧内容。",
        )

        # 第一次 LLM 调用返回提取结果（包含已有页面路径）
        # 第二次 LLM 调用返回合并后的内容
        mock_llm.chat.side_effect = [
            json.dumps(
                {
                    "concepts": ["Agent Loop"],
                    "pages": [
                        {
                            "path": "wiki/concepts/agent-loop.md",
                            "content": "新信息关于 Agent Loop",
                        },
                    ],
                }
            ),
            "---\ntitle: Agent Loop\n---\n\n# Agent Loop\n\n旧内容。\n\n## 新增\n\n新信息。",
        ]

        result = await compiler.ingest("raw/notes/test-article.md")
        assert len(result.pages_updated) == 1

    @pytest.mark.asyncio(loop_scope="function")
    async def test_ingest_rejects_unsafe_path(
        self, vault: Vault, compiler: Compiler, mock_llm
    ):
        """ingest 应该拒绝写入 raw/ 目录。"""
        mock_llm.chat.return_value = json.dumps(
            {
                "concepts": ["Hack"],
                "pages": [
                    {
                        "path": "raw/notes/hacked.md",
                        "content": "hacked content",
                    },
                ],
            }
        )

        result = await compiler.ingest("raw/notes/test-article.md")
        assert len(result.pages_created) == 0

    @pytest.mark.asyncio(loop_scope="function")
    async def test_ingest_file_not_found(self, compiler: Compiler):
        """ingest 不存在的文件应该抛异常。"""
        with pytest.raises(FileNotFoundError):
            await compiler.ingest("raw/notes/nonexistent.md")


# ---------------------------------------------------------------------------
# Save as Page 测试（mock LLM）
# ---------------------------------------------------------------------------


class TestSaveAsPage:
    @pytest.mark.asyncio(loop_scope="function")
    async def test_save_as_page(self, vault: Vault, compiler: Compiler, mock_llm):
        """save_as_page 应该创建 wiki 页面。"""
        mock_llm.chat.return_value = (
            "---\ntitle: My Summary\ntags: [summary]\n"
            "sources: []\nrelated: []\ncreated: 2026-04-15\n"
            "updated: 2026-04-15\nstatus: seedling\n---\n\n"
            "# My Summary\n\nThis is a summary."
        )

        page_path = await compiler.save_as_page(
            "My Summary",
            "This is the content to save.",
            "synthesis",
        )

        assert "wiki/synthesis/" in page_path
        content = vault.files.read_raw(page_path)
        assert "My Summary" in content

    @pytest.mark.asyncio(loop_scope="function")
    async def test_save_invalid_category(self, compiler: Compiler):
        """无效分类应该抛异常。"""
        with pytest.raises(ValueError, match="无效分类"):
            await compiler.save_as_page("Title", "Content", "invalid_category")


# ---------------------------------------------------------------------------
# Vault 集成测试
# ---------------------------------------------------------------------------


class TestVaultCompilerIntegration:
    @pytest.mark.asyncio(loop_scope="function")
    async def test_vault_ingest_no_llm(self, vault: Vault):
        """没有配置 LLM 时 ingest 应该返回提示信息。"""
        result = await vault.ingest("raw/notes/test-article.md")
        assert "未配置" in result

    @pytest.mark.asyncio(loop_scope="function")
    async def test_vault_save_page_no_llm(self, vault: Vault):
        """没有配置 LLM 时 save_page 应该返回提示信息。"""
        result = await vault.save_page("Title", "Content")
        assert "未配置" in result

    @pytest.mark.asyncio(loop_scope="function")
    async def test_vault_save_page_invalid_category(self, vault: Vault):
        """无效分类应该返回错误信息（LLM 未配置时先检查 LLM，再检查分类）。"""
        # LLM 未配置时，先返回 LLM 未配置提示
        result = await vault.save_page("Title", "Content", "bad")
        assert "未配置" in result or "无效分类" in result
