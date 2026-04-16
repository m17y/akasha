"""
测试飞书接入层 — serve/feishu.py

从 akasha-feishu 项目迁移，改为使用 Vault。
"""

import os
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from akasha.vault import Vault
from akasha.serve.feishu import FeishuHandlers


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def vault(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Vault:
    """创建测试 Vault。"""
    vault_path = tmp_path / "vault"
    monkeypatch.setenv("AKASHA_VAULT_PATH", str(vault_path))
    monkeypatch.setenv("AKASHA_CHROMA_DIR", str(tmp_path / "chroma"))
    monkeypatch.delenv("AKASHA_LLM_API_KEY", raising=False)  # 确保 LLM 未配置

    v = Vault(vault_path)
    v.init()

    docs = vault_path / "docs"
    (docs / "raw" / "notes" / "test.md").write_text(
        "---\ntitle: Test Note\ntags: [test]\n---\n\n# Test Note\n\n"
        "This is a test note with enough content to be indexed properly.\n",
        encoding="utf-8",
    )

    return v


@pytest.fixture
def handlers(vault: Vault) -> FeishuHandlers:
    return FeishuHandlers(vault)


# ---------------------------------------------------------------------------
# dispatch
# ---------------------------------------------------------------------------


class TestDispatch:
    def test_help(self, handlers: FeishuHandlers):
        result = handlers.dispatch("/help")
        assert "Akasha" in result
        assert "/search" in result

    def test_unknown_command(self, handlers: FeishuHandlers):
        result = handlers.dispatch("/unknown")
        assert "未知命令" in result

    def test_plain_text_as_search(self, handlers: FeishuHandlers):
        """非命令文本当作搜索处理。"""
        result = handlers.dispatch("Agent Loop")
        assert isinstance(result, str)

    def test_short_text_shows_help(self, handlers: FeishuHandlers):
        result = handlers.dispatch("hi")
        assert "/search" in result


# ---------------------------------------------------------------------------
# search
# ---------------------------------------------------------------------------


class TestSearch:
    def test_search_empty_query(self, handlers: FeishuHandlers):
        result = handlers.search("")
        assert "用法" in result

    def test_search_with_results(self, handlers: FeishuHandlers):
        result = handlers.search("test note")
        assert "找到" in result or "没有找到" in result

    def test_search_no_results(self, handlers: FeishuHandlers):
        result = handlers.search("xyznonexistent12345")
        assert isinstance(result, str)


# ---------------------------------------------------------------------------
# status
# ---------------------------------------------------------------------------


class TestStatus:
    def test_status(self, handlers: FeishuHandlers):
        result = handlers.status()
        assert "Akasha" in result
        assert "已索引" in result


# ---------------------------------------------------------------------------
# clip
# ---------------------------------------------------------------------------


class TestClip:
    def test_clip_empty_url(self, handlers: FeishuHandlers):
        result = handlers.clip("")
        assert "用法" in result

    def test_clip_success(self, handlers: FeishuHandlers):
        with patch.object(
            handlers.vault,
            "execute_skill",
            new_callable=AsyncMock,
        ) as mock:
            mock.return_value = "wiki/articles/test.md"
            result = handlers.clip("https://example.com")
        assert "已保存" in result

    def test_clip_failure(self, handlers: FeishuHandlers):
        with patch.object(
            handlers.vault,
            "execute_skill",
            new_callable=AsyncMock,
        ) as mock:
            mock.side_effect = Exception("network error")
            result = handlers.clip("https://bad.example.com")
        assert "失败" in result


# ---------------------------------------------------------------------------
# video
# ---------------------------------------------------------------------------


class TestVideo:
    def test_video_empty_url(self, handlers: FeishuHandlers):
        result = handlers.video("")
        assert "用法" in result

    def test_video_success(self, handlers: FeishuHandlers):
        with patch.object(
            handlers.vault,
            "execute_skill",
            new_callable=AsyncMock,
        ) as mock:
            mock.return_value = "wiki/entities/test-video.md"
            result = handlers.video("https://www.douyin.com/video/123")
        assert "已生成" in result


# ---------------------------------------------------------------------------
# ingest
# ---------------------------------------------------------------------------


class TestIngest:
    def test_ingest_empty_path(self, handlers: FeishuHandlers):
        result = handlers.ingest("")
        assert "用法" in result

    def test_ingest_no_llm(self, handlers: FeishuHandlers):
        result = handlers.ingest("raw/notes/test.md")
        assert "未配置" in result


# ---------------------------------------------------------------------------
# lint
# ---------------------------------------------------------------------------


class TestLint:
    def test_lint_empty_wiki(self, handlers: FeishuHandlers):
        result = handlers.lint()
        assert "通过" in result or "问题" in result
