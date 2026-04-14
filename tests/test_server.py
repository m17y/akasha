"""
Tests for akasha.server — MCP 工具函数集成测试。
"""

from pathlib import Path

import pytest

from akasha.config import Config
from akasha.indexer import Indexer
from akasha.store import VectorStore


@pytest.fixture
def setup_server(tmp_vault: Path, tmp_path: Path, monkeypatch):
    """构建索引并 monkeypatch server 模块的全局状态。"""
    cfg = Config(
        vault_path=tmp_vault.parent,  # vault_path → docs_dir = tmp_vault
        chroma_dir=tmp_path / "chroma_server",
    )
    store = VectorStore(chroma_dir=cfg.chroma_dir)
    indexer = Indexer(config=cfg, store=store)
    indexer.index_all(force=True)

    import akasha.server as srv

    monkeypatch.setattr(srv, "config", cfg)
    monkeypatch.setattr(srv, "_store", store)
    monkeypatch.setattr(srv, "_indexer", indexer)

    return store


# ============================================================================
# search_knowledge
# ============================================================================


@pytest.mark.asyncio
class TestSearchKnowledge:
    async def test_basic_search(self, setup_server):
        from akasha.server import search_knowledge

        result = await search_knowledge("Python 列表", top_k=3)
        assert isinstance(result, str)
        assert "找到" in result

    async def test_search_with_tags(self, setup_server):
        from akasha.server import search_knowledge

        result = await search_knowledge("数据", tags="hive")
        assert "找到" in result

    async def test_search_empty(self, tmp_path: Path, monkeypatch):
        """空索引搜索。"""
        import akasha.server as srv

        empty = tmp_path / "empty_vault"
        empty.mkdir()
        (empty / "docs").mkdir()
        cfg = Config(vault_path=empty, chroma_dir=tmp_path / "chroma_empty_srv")
        store = VectorStore(chroma_dir=cfg.chroma_dir)
        indexer = Indexer(config=cfg, store=store)
        monkeypatch.setattr(srv, "config", cfg)
        monkeypatch.setattr(srv, "_store", store)
        monkeypatch.setattr(srv, "_indexer", indexer)

        from akasha.server import search_knowledge

        result = await search_knowledge("anything")
        assert "为空" in result


# ============================================================================
# list_notes
# ============================================================================


@pytest.mark.asyncio
class TestListNotes:
    async def test_list_notes(self, setup_server):
        from akasha.server import list_notes

        result = await list_notes()
        assert "文件" in result
        assert "chunks" in result

    async def test_list_notes_empty(self, tmp_path: Path, monkeypatch):
        import akasha.server as srv

        empty = tmp_path / "empty2"
        empty.mkdir()
        (empty / "docs").mkdir()
        cfg = Config(vault_path=empty, chroma_dir=tmp_path / "chroma_empty2")
        store = VectorStore(chroma_dir=cfg.chroma_dir)
        monkeypatch.setattr(srv, "config", cfg)
        monkeypatch.setattr(srv, "_store", store)
        monkeypatch.setattr(srv, "_indexer", Indexer(config=cfg, store=store))

        from akasha.server import list_notes

        result = await list_notes()
        assert "为空" in result


# ============================================================================
# read_note
# ============================================================================


@pytest.mark.asyncio
class TestReadNote:
    async def test_read_existing(self, setup_server, tmp_vault: Path, monkeypatch):
        import akasha.server as srv

        monkeypatch.setattr(
            srv,
            "config",
            Config(
                vault_path=tmp_vault.parent,
                chroma_dir=srv.config.chroma_dir,
            ),
        )
        from akasha.server import read_note

        result = await read_note("bigdata/hive.md")
        assert "Hive" in result

    async def test_read_nonexistent(self, setup_server):
        from akasha.server import read_note

        result = await read_note("nonexistent.md")
        assert "不存在" in result

    async def test_read_path_traversal(
        self, setup_server, tmp_vault: Path, monkeypatch
    ):
        import akasha.server as srv

        monkeypatch.setattr(
            srv,
            "config",
            Config(
                vault_path=tmp_vault.parent,
                chroma_dir=srv.config.chroma_dir,
            ),
        )
        from akasha.server import read_note

        result = await read_note("../../etc/passwd")
        assert "不在 vault 范围内" in result or "不存在" in result


# ============================================================================
# refresh_index
# ============================================================================


@pytest.mark.asyncio
class TestRefreshIndex:
    async def test_refresh(self, setup_server):
        from akasha.server import refresh_index

        result = await refresh_index()
        assert "索引完成" in result

    async def test_force_refresh(self, setup_server):
        from akasha.server import refresh_index

        result = await refresh_index(force=True)
        assert "索引完成" in result
        assert "已索引" in result
