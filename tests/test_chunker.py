"""
Tests for akasha.chunker
"""

from pathlib import Path

import pytest

from akasha.chunker import (
    Chunk,
    ChunkMetadata,
    parse_frontmatter,
    scan_vault,
    split_by_headings,
)


# ============================================================================
# parse_frontmatter
# ============================================================================


class TestParseFrontmatter:
    def test_with_frontmatter(self):
        text = "---\ntitle: Hello\ntags:\n  - a\n  - b\n---\n\nBody here."
        meta, body = parse_frontmatter(text)
        assert meta["title"] == "Hello"
        assert meta["tags"] == ["a", "b"]
        assert body == "Body here."

    def test_without_frontmatter(self):
        text = "# Just a heading\n\nSome content."
        meta, body = parse_frontmatter(text)
        assert meta == {}
        assert body == text

    def test_invalid_yaml(self):
        text = "---\n: invalid: yaml: {{{\n---\n\nBody."
        meta, body = parse_frontmatter(text)
        assert meta == {}

    def test_empty_frontmatter(self):
        text = "---\n---\n\nBody only."
        meta, body = parse_frontmatter(text)
        assert meta == {}
        assert body == "Body only."


# ============================================================================
# ChunkMetadata
# ============================================================================


class TestChunkMetadata:
    def test_from_list_tags(self):
        meta = ChunkMetadata.from_frontmatter(
            {
                "tags": ["hive", "sql"],
                "title": "Hive",
                "date": "2026-04-14",
                "source": "https://example.com",
                "status": "developing",
            }
        )
        assert meta.tags == ["hive", "sql"]
        assert meta.title == "Hive"
        assert meta.date == "2026-04-14"
        assert meta.source == "https://example.com"
        assert meta.status == "developing"

    def test_from_string_tags(self):
        meta = ChunkMetadata.from_frontmatter({"tags": "agent, loop, design"})
        assert meta.tags == ["agent", "loop", "design"]

    def test_from_empty(self):
        meta = ChunkMetadata.from_frontmatter({})
        assert meta.tags == []
        assert meta.title == ""
        assert meta.date == ""

    def test_extra_fields(self):
        meta = ChunkMetadata.from_frontmatter(
            {
                "tags": [],
                "custom_field": "hello",
            }
        )
        assert meta.extra == {"custom_field": "hello"}


# ============================================================================
# Chunk
# ============================================================================


class TestChunk:
    def test_chunk_id_deterministic(self):
        c = Chunk(
            source_file="a.md",
            heading="Title",
            content="Hello world",
            metadata=ChunkMetadata(),
        )
        assert c.chunk_id == c.chunk_id

    def test_chunk_id_unique(self):
        c1 = Chunk(
            source_file="a.md", heading="T", content="AAA", metadata=ChunkMetadata()
        )
        c2 = Chunk(
            source_file="a.md", heading="T", content="BBB", metadata=ChunkMetadata()
        )
        assert c1.chunk_id != c2.chunk_id

    def test_chunk_id_hex(self):
        c = Chunk(
            source_file="x.md", heading="H", content="C" * 200, metadata=ChunkMetadata()
        )
        assert len(c.chunk_id) == 32
        int(c.chunk_id, 16)

    def test_to_store_metadata(self):
        meta = ChunkMetadata(
            tags=["a", "b"], date="2026-01-01", title="T", status="seedling"
        )
        c = Chunk(source_file="f.md", heading="H", content="C", metadata=meta)
        m = c.to_store_metadata()
        assert m["source"] == "f.md"
        assert m["heading"] == "H"
        assert m["tags"] == "a,b"
        assert m["date"] == "2026-01-01"
        assert m["title"] == "T"
        assert m["status"] == "seedling"


# ============================================================================
# split_by_headings
# ============================================================================


class TestSplitByHeadings:
    def test_splits_by_headings(self, tmp_vault: Path):
        hive_path = tmp_vault / "bigdata" / "hive.md"
        chunks = split_by_headings(hive_path, tmp_vault)

        assert len(chunks) >= 2
        for c in chunks:
            assert isinstance(c, Chunk)
            assert c.source_file == "bigdata/hive.md"
            assert c.metadata.title == "Hive 笔记"
            assert "hive" in c.metadata.tags

    def test_short_chunks_filtered(self, tmp_vault: Path):
        short_path = tmp_vault / "short.md"
        chunks = split_by_headings(short_path, tmp_vault)
        assert len(chunks) == 0

    def test_no_headings_whole_file(self, tmp_vault: Path):
        plain_path = tmp_vault / "plain.md"
        chunks = split_by_headings(plain_path, tmp_vault)
        assert len(chunks) == 1
        assert chunks[0].source_file == "plain.md"

    def test_unreadable_file(self, tmp_path: Path):
        bad_file = tmp_path / "binary.md"
        bad_file.write_bytes(b"\x80\x81\x82\x83" * 100)
        chunks = split_by_headings(bad_file, tmp_path)
        assert chunks == []

    def test_start_line_tracked(self, tmp_vault: Path):
        hive_path = tmp_vault / "bigdata" / "hive.md"
        chunks = split_by_headings(hive_path, tmp_vault)
        # start_line 应该 > 0
        for c in chunks:
            assert c.start_line > 0

    def test_string_tags_parsed(self, tmp_vault: Path):
        loop_path = tmp_vault / "agent" / "loop.md"
        chunks = split_by_headings(loop_path, tmp_vault)
        assert len(chunks) >= 2
        assert "agent" in chunks[0].metadata.tags
        assert chunks[0].metadata.source == "https://example.com/agent-loop"


# ============================================================================
# scan_vault
# ============================================================================


class TestScanVault:
    def test_scans_all_md_files(self, tmp_vault: Path):
        chunks = scan_vault(tmp_vault)
        sources = {c.source_file for c in chunks}
        assert "bigdata/hive.md" in sources
        assert "python/basics.md" in sources
        assert "plain.md" in sources
        assert "agent/loop.md" in sources

    def test_skips_git_dir(self, tmp_vault: Path):
        chunks = scan_vault(tmp_vault)
        for c in chunks:
            assert ".git" not in c.source_file

    def test_empty_vault(self, tmp_path: Path):
        chunks = scan_vault(tmp_path)
        assert chunks == []

    def test_custom_skip_dirs(self, tmp_vault: Path):
        # 把 "python" 加入跳过列表
        chunks = scan_vault(tmp_vault, skip_dirs={"python", ".git"})
        sources = {c.source_file for c in chunks}
        assert "python/basics.md" not in sources
        assert "bigdata/hive.md" in sources
