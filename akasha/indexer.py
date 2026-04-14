"""
文档索引器 — 扫描 vault → 切分 → 存入向量库。

职责:
- 全量索引（首次启动）
- 增量更新（只处理修改过的文件）
- 记录每个文件的索引时间，用于增量判断
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from pathlib import Path

from .chunker import scan_vault, split_by_headings
from .config import Config
from .store import VectorStore


# ---------------------------------------------------------------------------
# 数据结构
# ---------------------------------------------------------------------------


@dataclass
class IndexStats:
    """索引操作统计。"""

    total_files: int = 0
    files_indexed: int = 0
    files_skipped: int = 0
    files_removed: int = 0
    total_chunks: int = 0
    duration_seconds: float = 0.0

    def summary(self) -> str:
        parts = [f"索引完成 ({self.duration_seconds:.1f}s):"]
        parts.append(
            f"  文件: {self.files_indexed} 已索引, {self.files_skipped} 已跳过, {self.files_removed} 已删除"
        )
        parts.append(f"  Chunks: {self.total_chunks}")
        return "\n".join(parts)


# ---------------------------------------------------------------------------
# 索引时间记录（用于增量更新）
# ---------------------------------------------------------------------------

_INDEX_META_FILE = ".index_meta.json"


def _load_index_meta(chroma_dir: Path) -> dict[str, float]:
    """加载文件索引时间记录。{相对路径: mtime}"""
    meta_path = chroma_dir / _INDEX_META_FILE
    if meta_path.exists():
        try:
            return json.loads(meta_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            pass
    return {}


def _save_index_meta(chroma_dir: Path, meta: dict[str, float]) -> None:
    """保存文件索引时间记录。"""
    meta_path = chroma_dir / _INDEX_META_FILE
    meta_path.parent.mkdir(parents=True, exist_ok=True)
    meta_path.write_text(
        json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8"
    )


# ---------------------------------------------------------------------------
# Indexer
# ---------------------------------------------------------------------------


class Indexer:
    """文档索引器。"""

    def __init__(self, config: Config, store: VectorStore):
        self.config = config
        self.store = store

    def index_all(self, force: bool = False) -> IndexStats:
        """全量索引。

        Args:
            force: 是否强制重建（忽略增量判断）

        Returns:
            索引统计
        """
        start = time.time()
        stats = IndexStats()

        docs = self.config.docs_dir
        print(f"[indexer] 扫描 docs: {docs}")

        # 扫描所有 md 文件
        md_files: list[Path] = []
        if docs.exists():
            for md_file in docs.rglob("*.md"):
                if any(part in self.config.skip_dirs for part in md_file.parts):
                    continue
                md_files.append(md_file)

        stats.total_files = len(md_files)
        print(f"[indexer] 找到 {stats.total_files} 个 .md 文件")

        if force:
            # 全量重建: 清空旧数据
            self.store.clear()
            index_meta: dict[str, float] = {}
        else:
            index_meta = _load_index_meta(self.config.chroma_dir)

        # 处理每个文件
        all_current_sources: set[str] = set()
        for md_file in md_files:
            rel_path = str(md_file.relative_to(docs))
            all_current_sources.add(rel_path)
            file_mtime = md_file.stat().st_mtime

            # 增量判断: 文件未修改则跳过
            if not force and rel_path in index_meta:
                if index_meta[rel_path] >= file_mtime:
                    stats.files_skipped += 1
                    continue

            # 需要索引: 先删除旧 chunks（如果有）
            self.store.delete_by_file(rel_path)

            # 切分 + 写入
            chunks = split_by_headings(md_file, docs, self.config.min_chunk_length)
            if chunks:
                self.store.upsert_chunks(
                    chunks,
                    batch_size=self.config.batch_size,
                    max_content_length=self.config.max_chunk_store_length,
                )

            stats.files_indexed += 1
            stats.total_chunks += len(chunks)
            index_meta[rel_path] = file_mtime

        # 清理已删除的文件
        removed_sources = set(index_meta.keys()) - all_current_sources
        for src in removed_sources:
            self.store.delete_by_file(src)
            del index_meta[src]
            stats.files_removed += 1

        # 保存索引元数据
        _save_index_meta(self.config.chroma_dir, index_meta)

        stats.total_chunks = self.store.count()
        stats.duration_seconds = time.time() - start
        print(f"[indexer] {stats.summary()}")
        return stats

    def index_file(self, file_path: Path) -> int:
        """索引单个文件。

        Args:
            file_path: 文件绝对路径

        Returns:
            chunk 数量
        """
        docs = self.config.docs_dir
        rel_path = str(file_path.relative_to(docs))

        # 删除旧 chunks
        self.store.delete_by_file(rel_path)

        # 切分 + 写入
        chunks = split_by_headings(file_path, docs, self.config.min_chunk_length)
        if chunks:
            self.store.upsert_chunks(
                chunks,
                batch_size=self.config.batch_size,
                max_content_length=self.config.max_chunk_store_length,
            )

        # 更新索引元数据
        index_meta = _load_index_meta(self.config.chroma_dir)
        index_meta[rel_path] = file_path.stat().st_mtime
        _save_index_meta(self.config.chroma_dir, index_meta)

        return len(chunks)

    def refresh(self) -> IndexStats:
        """增量更新 — 只处理修改过的文件。"""
        return self.index_all(force=False)
