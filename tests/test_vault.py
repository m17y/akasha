"""
测试 Vault 核心功能 — Phase 1。

覆盖:
- Vault 初始化
- 文件读取（正常 / 分页 / 路径安全）
- 列出笔记
- 搜索
- 索引刷新
- 状态查询
"""

import os
import pytest
from pathlib import Path

from akasha.vault import Vault
from akasha.config import Config
from akasha.storage.files import FileStore
from akasha.storage.index import VectorIndex


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def vault(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Vault:
    """创建一个使用临时目录的 Vault 实例。"""
    vault_path = tmp_path / "vault"
    monkeypatch.setenv("AKASHA_VAULT_PATH", str(vault_path))
    monkeypatch.setenv("AKASHA_CHROMA_DIR", str(tmp_path / "chroma"))

    v = Vault(vault_path)
    v.init()

    # 写入测试文件
    docs = vault_path / "docs"

    note1 = docs / "raw" / "notes" / "hive.md"
    note1.write_text(
        """\
---
tags:
  - hive
  - sql
title: Hive 笔记
---

# Hive 概述

Hive 是一个基于 Hadoop 的数据仓库工具。

## 窗口函数

ROW_NUMBER, RANK, DENSE_RANK 是常用的窗口函数。

## 分区表

分区表通过 PARTITION BY 子句实现。
""",
        encoding="utf-8",
    )

    note2 = docs / "raw" / "notes" / "agent-loop.md"
    note2.write_text(
        """\
---
tags: agent, loop
title: Agent Loop
---

# Agent Loop

Agent Loop 是一种设计模式，循环执行 Think Act Observe。

## 实现要点

Think 决定下一步，Act 执行操作，Observe 观察结果。
""",
        encoding="utf-8",
    )

    return v


# ---------------------------------------------------------------------------
# 初始化
# ---------------------------------------------------------------------------


class TestInit:
    def test_init_creates_dirs(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        vault_path = tmp_path / "new_vault"
        monkeypatch.setenv("AKASHA_VAULT_PATH", str(vault_path))
        monkeypatch.setenv("AKASHA_CHROMA_DIR", str(tmp_path / "chroma"))

        v = Vault(vault_path)
        v.init()

        assert (vault_path / "docs").exists()
        assert (vault_path / "docs" / "raw" / "notes").exists()
        assert (vault_path / "docs" / "wiki" / "concepts").exists()
        assert (vault_path / "docs" / "schema.md").exists()
        assert (vault_path / "docs" / "index.md").exists()
        assert (vault_path / "docs" / "log.md").exists()

    def test_init_idempotent(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        vault_path = tmp_path / "vault"
        monkeypatch.setenv("AKASHA_VAULT_PATH", str(vault_path))
        monkeypatch.setenv("AKASHA_CHROMA_DIR", str(tmp_path / "chroma"))

        v = Vault(vault_path)
        v.init()
        v.init()  # 第二次调用不应报错
        assert (vault_path / "docs" / "schema.md").exists()


# ---------------------------------------------------------------------------
# 文件读取
# ---------------------------------------------------------------------------


class TestRead:
    def test_read_note(self, vault: Vault):
        result = vault.read("raw/notes/hive.md")
        assert "Hive" in result.content
        assert not result.truncated

    def test_read_not_found(self, vault: Vault):
        with pytest.raises(FileNotFoundError):
            vault.read("nonexistent.md")

    def test_read_path_traversal(self, vault: Vault):
        with pytest.raises(ValueError, match="不合法"):
            vault.read("../../../etc/passwd")

    def test_read_formatted(self, vault: Vault):
        text = vault.read_formatted("raw/notes/hive.md")
        assert "Hive" in text

    def test_read_formatted_not_found(self, vault: Vault):
        text = vault.read_formatted("nonexistent.md")
        assert "不存在" in text


# ---------------------------------------------------------------------------
# 列出笔记
# ---------------------------------------------------------------------------


class TestListNotes:
    def test_list_notes(self, vault: Vault):
        notes = vault.list_notes()
        assert len(notes) > 0
        sources = [n["source"] for n in notes]
        assert any("hive" in s for s in sources)

    def test_list_notes_formatted(self, vault: Vault):
        text = vault.list_notes_formatted()
        assert "hive" in text
        assert "chunks" in text


# ---------------------------------------------------------------------------
# 搜索
# ---------------------------------------------------------------------------


class TestSearch:
    def test_search_basic(self, vault: Vault):
        results = vault.search("窗口函数")
        assert len(results) > 0
        assert any("hive" in r.source.lower() for r in results)

    def test_search_with_tags(self, vault: Vault):
        results = vault.search("数据", tags="hive")
        # 应该只返回带 hive tag 的结果
        for r in results:
            assert "hive" in r.tags

    def test_search_no_results(self, vault: Vault):
        # 搜索一个完全不相关的内容
        results = vault.search("量子纠缠超导体碳纳米管")
        # 可能有结果（语义搜索会返回最近的），但分数应该较低
        # 这里只验证不抛异常
        assert isinstance(results, list)

    def test_search_formatted(self, vault: Vault):
        text = vault.search_formatted("Agent Loop")
        assert "找到" in text or "没有找到" in text


# ---------------------------------------------------------------------------
# 索引
# ---------------------------------------------------------------------------


class TestIndex:
    def test_refresh_index(self, vault: Vault):
        stats = vault.refresh_index()
        assert stats.total_chunks > 0

    def test_force_rebuild(self, vault: Vault):
        vault.ensure_indexed()
        stats = vault.refresh_index(force=True)
        assert stats.files_indexed > 0
        assert stats.total_chunks > 0


# ---------------------------------------------------------------------------
# 状态
# ---------------------------------------------------------------------------


class TestStatus:
    def test_status(self, vault: Vault):
        s = vault.status()
        assert "vault_path" in s
        assert "files_count" in s
        assert "chunks_count" in s
        assert s["files_count"] > 0

    def test_status_formatted(self, vault: Vault):
        text = vault.status_formatted()
        assert "Akasha 状态" in text
        assert "已索引" in text


# ---------------------------------------------------------------------------
# FileStore 直接测试
# ---------------------------------------------------------------------------


class TestFileStore:
    def test_write_wiki_ok(self, vault: Vault):
        vault.files.write_wiki(
            "wiki/concepts/test-concept.md",
            "# Test Concept\n\nThis is a test.",
        )
        result = vault.read("wiki/concepts/test-concept.md")
        assert "Test Concept" in result.content

    def test_write_wiki_rejects_raw(self, vault: Vault):
        with pytest.raises(ValueError, match="wiki"):
            vault.files.write_wiki("raw/notes/hack.md", "hacked")

    def test_write_wiki_rejects_traversal(self, vault: Vault):
        with pytest.raises(ValueError, match="不合法"):
            vault.files.write_wiki("wiki/../../etc/passwd", "hacked")

    def test_list_files(self, vault: Vault):
        files = vault.files.list_files("raw")
        assert any("hive" in f for f in files)

    def test_list_wiki_pages_empty(self, vault: Vault):
        pages = vault.files.list_wiki_pages()
        # 初始化后 wiki 目录下没有 .md 文件
        assert isinstance(pages, list)


# ---------------------------------------------------------------------------
# VectorIndex 直接测试
# ---------------------------------------------------------------------------


class TestVectorIndex:
    def test_build_and_search(self, vault: Vault):
        stats = vault.index.build(force=True)
        assert stats.total_chunks > 0

        results = vault.index.search("Hive 窗口函数", top_k=3)
        assert len(results) > 0

    def test_incremental_build(self, vault: Vault):
        vault.index.build(force=True)
        stats = vault.index.build(force=False)
        # 增量构建应该跳过所有文件
        assert stats.files_indexed == 0
        assert stats.files_skipped > 0
