"""
Tests for L4 安全 / L5 韧性 / L6 可观测。
"""

import json
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from akasha.config import Config
from akasha.ingester import Ingester
from akasha.events import emit, Timer


# ============================================================================
# Fixtures
# ============================================================================


@pytest.fixture
def secure_vault(tmp_path: Path) -> Path:
    """创建带完整 wiki 结构的 vault（用于安全测试）。"""
    docs = tmp_path / "docs"
    (docs / "raw" / "analysis").mkdir(parents=True)
    (docs / "wiki" / "concepts").mkdir(parents=True)
    (docs / "wiki" / "entities").mkdir(parents=True)
    (docs / "wiki" / "synthesis").mkdir(parents=True)
    (docs / "index.md").write_text("# Index\n", encoding="utf-8")
    (docs / "log.md").write_text("# Log\n---\n", encoding="utf-8")
    (docs / "raw" / "analysis" / "test.md").write_text(
        "# Test\n\nContent.", encoding="utf-8"
    )
    return tmp_path


@pytest.fixture
def secure_config(secure_vault: Path, tmp_path: Path) -> Config:
    return Config(
        vault_path=secure_vault,
        chroma_dir=tmp_path / "chroma",
        llm_api_key="test-key",
    )


@pytest.fixture
def ingester(secure_config: Config) -> Ingester:
    ing = Ingester.__new__(Ingester)
    ing.config = secure_config
    ing.llm = AsyncMock()
    return ing


# ============================================================================
# L4 安全: _validate_write_path
# ============================================================================


class TestValidateWritePath:
    def test_valid_wiki_path(self, ingester: Ingester):
        assert ingester._validate_write_path("wiki/concepts/test.md") is True

    def test_valid_nested_wiki_path(self, ingester: Ingester):
        assert ingester._validate_write_path("wiki/entities/sub/deep.md") is True

    def test_reject_raw_path(self, ingester: Ingester):
        """不允许写入 raw/ 目录。"""
        assert ingester._validate_write_path("raw/analysis/evil.md") is False

    def test_reject_dotdot_traversal(self, ingester: Ingester):
        """拒绝 .. 路径穿越。"""
        assert ingester._validate_write_path("wiki/../raw/evil.md") is False
        assert ingester._validate_write_path("../../../etc/passwd") is False

    def test_reject_root_files(self, ingester: Ingester):
        """不允许写入 docs/ 根目录的文件。"""
        assert ingester._validate_write_path("schema.md") is False
        assert ingester._validate_write_path("index.md") is False

    def test_reject_empty_path(self, ingester: Ingester):
        assert ingester._validate_write_path("") is False

    def test_reject_non_wiki_prefix(self, ingester: Ingester):
        assert ingester._validate_write_path("assets/video/evil.mp4") is False


class TestIngestSecurity:
    @pytest.mark.asyncio
    async def test_ingest_blocks_raw_write(
        self, ingester: Ingester, secure_vault: Path
    ):
        """LLM 返回写 raw/ 的路径时应被拒绝。"""
        ingester.llm.chat.return_value = json.dumps(
            {
                "concepts": ["Evil"],
                "pages": [
                    {
                        "path": "raw/analysis/overwrite.md",
                        "content": "# Overwritten!",
                    }
                ],
            }
        )

        result = await ingester.ingest("raw/analysis/test.md")
        # 不应创建任何页面
        assert len(result.pages_created) == 0
        # raw 文件不应被篡改
        raw_file = secure_vault / "docs" / "raw" / "analysis" / "test.md"
        assert "Content." in raw_file.read_text()

    @pytest.mark.asyncio
    async def test_ingest_blocks_path_traversal(
        self, ingester: Ingester, secure_vault: Path
    ):
        """LLM 返回 ../xxx 的路径时应被拒绝。"""
        ingester.llm.chat.return_value = json.dumps(
            {
                "concepts": ["Evil"],
                "pages": [
                    {
                        "path": "wiki/../../etc/evil.md",
                        "content": "# Evil!",
                    }
                ],
            }
        )

        result = await ingester.ingest("raw/analysis/test.md")
        assert len(result.pages_created) == 0


# ============================================================================
# L4 安全: read_note
# ============================================================================


@pytest.mark.asyncio
class TestReadNoteSecurity:
    async def test_path_traversal_blocked(self, monkeypatch):
        """.. 路径穿越在检查存在之前就被拦截。"""
        import akasha.server as srv

        cfg = Config(vault_path=Path("/tmp/test_vault"))
        monkeypatch.setattr(srv, "config", cfg)

        from akasha.server import read_note

        result = await read_note("../../etc/passwd")
        assert "不在 vault 范围内" in result

    async def test_offset_pagination(self, tmp_path: Path, monkeypatch):
        """read_note 支持 offset 分页。"""
        import akasha.server as srv

        vault = tmp_path / "vault"
        docs = vault / "docs"
        docs.mkdir(parents=True)
        (docs / "big.md").write_text("A" * 20000, encoding="utf-8")

        cfg = Config(vault_path=vault)
        monkeypatch.setattr(srv, "config", cfg)

        from akasha.server import read_note

        result1 = await read_note("big.md", offset=0)
        assert "截断" in result1
        assert "offset=10000" in result1

        result2 = await read_note("big.md", offset=10000)
        assert "截断" in result2 or len(result2) <= 10001  # 第二页可能不截断


# ============================================================================
# L5 韧性: LLM retry 配置
# ============================================================================


class TestLLMResilience:
    def test_llm_client_has_retry(self):
        """LLMClient 应配置 max_retries 和 timeout。"""
        from akasha.llm import LLMClient

        cfg = Config(
            llm_api_key="test",
            llm_base_url="https://api.example.com/v1",
        )
        client = LLMClient(cfg)
        # openai SDK 的 _client 应有 max_retries 配置
        assert client._client.max_retries == 3
        # timeout 可能是 float 或 Timeout 对象
        timeout = client._client.timeout
        if isinstance(timeout, (int, float)):
            assert timeout == 120.0
        else:
            assert timeout.read == 120.0


# ============================================================================
# L6 可观测: events
# ============================================================================


class TestEvents:
    def test_emit_basic(self, capsys):
        emit("test_event", key1="value1", key2=42)
        captured = capsys.readouterr()
        assert "test_event" in captured.err
        assert "key1=value1" in captured.err
        assert "key2=42" in captured.err

    def test_emit_truncates_long_values(self, capsys):
        emit("test_event", long_val="x" * 200)
        captured = capsys.readouterr()
        assert '..."' in captured.err

    def test_emit_float_format(self, capsys):
        emit("test_event", duration=1.23456)
        captured = capsys.readouterr()
        assert "duration=1.23" in captured.err

    def test_timer(self):
        import time

        with Timer() as t:
            time.sleep(0.05)
        assert t.elapsed >= 0.04
        assert t.elapsed < 1.0
