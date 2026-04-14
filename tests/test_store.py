"""
Tests for akasha.store
"""

from pathlib import Path

import pytest

from akasha.chunker import Chunk, ChunkMetadata, split_by_headings, scan_vault
from akasha.store import VectorStore, SearchResult


@pytest.fixture
def store(tmp_path: Path) -> VectorStore:
    """创建一个临时 VectorStore。"""
    return VectorStore(chroma_dir=tmp_path / "chroma", collection_name="test")


@pytest.fixture
def sample_chunks(tmp_vault: Path) -> list[Chunk]:
    """从临时 vault 扫描获取 chunks。"""
    return scan_vault(tmp_vault)


# ============================================================================
# VectorStore 基础
# ============================================================================


class TestVectorStoreBasic:
    def test_empty_store(self, store: VectorStore):
        assert store.count() == 0

    def test_upsert_and_count(self, store: VectorStore, sample_chunks: list[Chunk]):
        count = store.upsert_chunks(sample_chunks)
        assert count == len(sample_chunks)
        assert store.count() == len(sample_chunks)

    def test_upsert_idempotent(self, store: VectorStore, sample_chunks: list[Chunk]):
        """重复 upsert 相同 chunks 不会增加数量。"""
        store.upsert_chunks(sample_chunks)
        count1 = store.count()
        store.upsert_chunks(sample_chunks)
        count2 = store.count()
        assert count1 == count2

    def test_clear(self, store: VectorStore, sample_chunks: list[Chunk]):
        store.upsert_chunks(sample_chunks)
        assert store.count() > 0
        cleared = store.clear()
        assert cleared > 0
        assert store.count() == 0


# ============================================================================
# 搜索
# ============================================================================


class TestVectorStoreSearch:
    def test_search_returns_results(
        self, store: VectorStore, sample_chunks: list[Chunk]
    ):
        store.upsert_chunks(sample_chunks)
        results = store.search("窗口函数", top_k=3)
        assert len(results) > 0
        assert all(isinstance(r, SearchResult) for r in results)

    def test_search_relevance(self, store: VectorStore, sample_chunks: list[Chunk]):
        store.upsert_chunks(sample_chunks)
        results = store.search("Hive 窗口函数", top_k=3)
        # 最相关的结果应该来自 hive.md
        assert any("hive" in r.source for r in results)

    def test_search_empty_store(self, store: VectorStore):
        results = store.search("anything")
        assert results == []

    def test_search_with_tag_filter(
        self, store: VectorStore, sample_chunks: list[Chunk]
    ):
        store.upsert_chunks(sample_chunks)
        # 只搜有 "hive" tag 的内容
        results = store.search("数据", top_k=10, tags=["hive"])
        for r in results:
            assert "hive" in r.tags

    def test_search_with_multiple_tags(
        self, store: VectorStore, sample_chunks: list[Chunk]
    ):
        store.upsert_chunks(sample_chunks)
        # 搜带 "agent" 或 "hive" tag 的内容
        results = store.search("设计模式", top_k=10, tags=["agent", "hive"])
        assert len(results) > 0

    def test_search_score_range(self, store: VectorStore, sample_chunks: list[Chunk]):
        store.upsert_chunks(sample_chunks)
        results = store.search("Python 列表", top_k=3)
        for r in results:
            assert -1 <= r.score <= 1  # cosine similarity 范围


# ============================================================================
# 删除
# ============================================================================


class TestVectorStoreDelete:
    def test_delete_by_file(self, store: VectorStore, sample_chunks: list[Chunk]):
        store.upsert_chunks(sample_chunks)
        initial = store.count()
        deleted = store.delete_by_file("bigdata/hive.md")
        assert deleted > 0
        assert store.count() < initial

    def test_delete_nonexistent(self, store: VectorStore, sample_chunks: list[Chunk]):
        store.upsert_chunks(sample_chunks)
        deleted = store.delete_by_file("nonexistent.md")
        assert deleted == 0


# ============================================================================
# get_all_sources
# ============================================================================


class TestVectorStoreGetSources:
    def test_get_all_sources(self, store: VectorStore, sample_chunks: list[Chunk]):
        store.upsert_chunks(sample_chunks)
        sources = store.get_all_sources()
        assert len(sources) > 0
        source_names = {s["source"] for s in sources}
        assert "bigdata/hive.md" in source_names

    def test_source_info_fields(self, store: VectorStore, sample_chunks: list[Chunk]):
        store.upsert_chunks(sample_chunks)
        sources = store.get_all_sources()
        for info in sources:
            assert "source" in info
            assert "chunk_count" in info
            assert info["chunk_count"] > 0

    def test_empty_store_sources(self, store: VectorStore):
        sources = store.get_all_sources()
        assert sources == []
