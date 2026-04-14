"""
Tests for akasha.indexer
"""

import time
from pathlib import Path

import pytest

from akasha.config import Config
from akasha.indexer import (
    Indexer,
    IndexStats,
    _load_index_meta,
    _save_index_meta,
)
from akasha.store import VectorStore


@pytest.fixture
def config(tmp_vault: Path, tmp_path: Path) -> Config:
    """创建测试用 Config。vault_path 指向 tmp_vault 的父目录，docs_dir 即 tmp_vault。"""
    return Config(
        vault_path=tmp_vault.parent,
        chroma_dir=tmp_path / "chroma",
    )


@pytest.fixture
def store(config: Config) -> VectorStore:
    return VectorStore(chroma_dir=config.chroma_dir)


@pytest.fixture
def indexer(config: Config, store: VectorStore) -> Indexer:
    return Indexer(config=config, store=store)


# ============================================================================
# index_meta 持久化
# ============================================================================


class TestIndexMeta:
    def test_save_and_load(self, tmp_path: Path):
        meta = {"file1.md": 1000.0, "file2.md": 2000.0}
        _save_index_meta(tmp_path, meta)
        loaded = _load_index_meta(tmp_path)
        assert loaded == meta

    def test_load_nonexistent(self, tmp_path: Path):
        meta = _load_index_meta(tmp_path / "nonexistent")
        assert meta == {}

    def test_load_corrupt(self, tmp_path: Path):
        meta_path = tmp_path / ".index_meta.json"
        meta_path.write_text("{invalid json", encoding="utf-8")
        meta = _load_index_meta(tmp_path)
        assert meta == {}


# ============================================================================
# Indexer.index_all
# ============================================================================


class TestIndexerAll:
    def test_full_index(self, indexer: Indexer, store: VectorStore):
        stats = indexer.index_all(force=True)
        assert stats.total_files > 0
        assert stats.files_indexed > 0
        assert stats.total_chunks > 0
        assert store.count() > 0

    def test_incremental_skips(self, indexer: Indexer, store: VectorStore):
        """第二次增量索引应跳过未修改的文件。"""
        stats1 = indexer.index_all(force=True)
        stats2 = indexer.index_all(force=False)
        # 第二次应该跳过所有文件
        assert stats2.files_skipped == stats1.total_files
        assert stats2.files_indexed == 0

    def test_force_rebuild(self, indexer: Indexer, store: VectorStore):
        """强制重建应重新索引所有文件。"""
        indexer.index_all(force=True)
        count1 = store.count()
        stats = indexer.index_all(force=True)
        assert stats.files_indexed > 0
        assert store.count() == count1

    def test_detects_modified_file(
        self, indexer: Indexer, store: VectorStore, tmp_vault: Path
    ):
        """修改文件后增量索引应检测到变化。"""
        indexer.index_all(force=True)
        count1 = store.count()

        # 等待 1 秒确保 mtime 变化
        time.sleep(0.1)

        # 修改一个文件
        hive_path = tmp_vault / "bigdata" / "hive.md"
        content = hive_path.read_text(encoding="utf-8")
        hive_path.write_text(
            content
            + "\n## 新增章节\n\n这是新增的内容，用于测试增量更新是否能检测到。\n",
            encoding="utf-8",
        )

        stats = indexer.index_all(force=False)
        assert stats.files_indexed >= 1  # 至少修改的那个文件被重新索引
        assert stats.files_skipped >= 1  # 其他文件被跳过

    def test_detects_deleted_file(
        self, indexer: Indexer, store: VectorStore, tmp_vault: Path
    ):
        """删除文件后增量索引应清理对应 chunks。"""
        indexer.index_all(force=True)

        # 删除一个文件
        plain_path = tmp_vault / "plain.md"
        plain_path.unlink()

        stats = indexer.index_all(force=False)
        assert stats.files_removed >= 1

        # 确认 plain.md 的 chunks 被删除
        sources = store.get_all_sources()
        source_names = {s["source"] for s in sources}
        assert "plain.md" not in source_names

    def test_empty_vault(self, tmp_path: Path):
        """空 vault 应构建空索引。"""
        empty = tmp_path / "empty"
        empty.mkdir()
        (empty / "docs").mkdir()
        cfg = Config(vault_path=empty, chroma_dir=tmp_path / "chroma_empty")
        s = VectorStore(chroma_dir=cfg.chroma_dir)
        idx = Indexer(config=cfg, store=s)

        stats = idx.index_all(force=True)
        assert stats.total_files == 0
        assert stats.total_chunks == 0

    def test_stats_summary(self, indexer: Indexer):
        stats = indexer.index_all(force=True)
        summary = stats.summary()
        assert "索引完成" in summary
        assert "已索引" in summary


# ============================================================================
# Indexer.index_file
# ============================================================================


class TestIndexerFile:
    def test_index_single_file(
        self, indexer: Indexer, store: VectorStore, tmp_vault: Path
    ):
        hive_path = tmp_vault / "bigdata" / "hive.md"
        count = indexer.index_file(hive_path)
        assert count > 0
        assert store.count() == count

    def test_reindex_replaces(
        self, indexer: Indexer, store: VectorStore, tmp_vault: Path
    ):
        """重复索引同一文件不会增加 chunk 数量。"""
        hive_path = tmp_vault / "bigdata" / "hive.md"
        count1 = indexer.index_file(hive_path)
        count2 = indexer.index_file(hive_path)
        assert count1 == count2
        assert store.count() == count1


# ============================================================================
# Indexer.refresh
# ============================================================================


class TestIndexerRefresh:
    def test_refresh_is_incremental(self, indexer: Indexer, store: VectorStore):
        """refresh 是 index_all(force=False) 的快捷方式。"""
        indexer.index_all(force=True)
        stats = indexer.refresh()
        assert stats.files_skipped > 0
        assert stats.files_indexed == 0
