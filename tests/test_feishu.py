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
def vault(tmp_path: Path) -> Vault:
    """创建测试 Vault。"""
    vault_path = tmp_path / "vault"
    os.environ["AKASHA_VAULT_PATH"] = str(vault_path)
    os.environ["AKASHA_CHROMA_DIR"] = str(tmp_path / "chroma")
    os.environ.pop("AKASHA_LLM_API_KEY", None)  # 确保 LLM 未配置

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


@pytest.mark.asyncio(loop_scope="function")
class TestDispatch:
    async def test_help(self, handlers: FeishuHandlers):
        result = await handlers.dispatch("/help")
        assert "Akasha" in result
        assert "/search" in result

    async def test_unknown_command(self, handlers: FeishuHandlers):
        result = await handlers.dispatch("/unknown")
        assert "未知命令" in result

    async def test_plain_text_as_search(self, handlers: FeishuHandlers):
        """非命令文本当作搜索处理。"""
        result = await handlers.dispatch("Agent Loop")
        assert isinstance(result, str)

    async def test_short_text_shows_help(self, handlers: FeishuHandlers):
        result = await handlers.dispatch("hi")
        assert "/search" in result


# ---------------------------------------------------------------------------
# search
# ---------------------------------------------------------------------------


@pytest.mark.asyncio(loop_scope="function")
class TestSearch:
    async def test_search_empty_query(self, handlers: FeishuHandlers):
        result = await handlers.search("")
        assert "用法" in result

    async def test_search_with_results(self, handlers: FeishuHandlers):
        result = await handlers.search("test note")
        assert "找到" in result or "没有找到" in result

    async def test_search_no_results(self, handlers: FeishuHandlers):
        result = await handlers.search("xyznonexistent12345")
        assert isinstance(result, str)


# ---------------------------------------------------------------------------
# status
# ---------------------------------------------------------------------------


@pytest.mark.asyncio(loop_scope="function")
class TestStatus:
    async def test_status(self, handlers: FeishuHandlers):
        result = await handlers.status()
        assert "vault" in result
        assert "已索引" in result


# ---------------------------------------------------------------------------
# clip
# ---------------------------------------------------------------------------


@pytest.mark.asyncio(loop_scope="function")
class TestClip:
    async def test_clip_empty_url(self, handlers: FeishuHandlers):
        result = await handlers.clip("")
        assert "用法" in result

    async def test_clip_success(self, handlers: FeishuHandlers):
        with patch.object(
            handlers.vault,
            "execute_skill",
            new_callable=AsyncMock,
        ) as mock:
            mock.return_value = "wiki/articles/test.md"
            result = await handlers.clip("https://example.com")
        assert "已保存" in result

    async def test_clip_failure(self, handlers: FeishuHandlers):
        with patch.object(
            handlers.vault,
            "execute_skill",
            new_callable=AsyncMock,
        ) as mock:
            mock.side_effect = Exception("network error")
            result = await handlers.clip("https://bad.example.com")
        assert "失败" in result


# ---------------------------------------------------------------------------
# video
# ---------------------------------------------------------------------------


@pytest.mark.asyncio(loop_scope="function")
class TestVideo:
    async def test_video_empty_url(self, handlers: FeishuHandlers):
        result = await handlers.video("")
        assert "用法" in result

    async def test_video_success(self, handlers: FeishuHandlers):
        with patch.object(
            handlers.vault,
            "execute_skill",
            new_callable=AsyncMock,
        ) as mock:
            mock.return_value = "wiki/entities/test-video.md"
            result = await handlers.video("https://www.douyin.com/video/123")
        assert "已生成" in result


# ---------------------------------------------------------------------------
# ingest
# ---------------------------------------------------------------------------


@pytest.mark.asyncio(loop_scope="function")
class TestIngest:
    async def test_ingest_empty_path(self, handlers: FeishuHandlers):
        result = await handlers.ingest("")
        assert "用法" in result

    async def test_ingest_no_llm(self, handlers: FeishuHandlers):
        result = await handlers.ingest("raw/notes/test.md")
        assert "未配置" in result


# ---------------------------------------------------------------------------
# lint
# ---------------------------------------------------------------------------


@pytest.mark.asyncio(loop_scope="function")
class TestLint:
    async def test_lint_empty_wiki(self, handlers: FeishuHandlers):
        result = await handlers.lint()
        assert "通过" in result or "问题" in result
