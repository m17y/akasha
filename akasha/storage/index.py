"""
向量索引 — 合并 chunker + store + indexer。

职责:
- Markdown 按标题切分为 chunks
- ChromaDB 向量存储（embedding、upsert、search、delete）
- 增量索引（基于文件 mtime）
- 全量重建

对外暴露一个 VectorIndex 类，不需要关心底层细节。
"""

from __future__ import annotations

import hashlib
import json
import re
import time
from dataclasses import dataclass, field
from pathlib import Path

import chromadb
import yaml

from ..config import Config


# ---------------------------------------------------------------------------
# 数据结构
# ---------------------------------------------------------------------------


@dataclass
class ChunkMetadata:
    """从 frontmatter 提取的结构化元数据。"""

    tags: list[str] = field(default_factory=list)
    date: str = ""
    source: str = ""
    status: str = ""
    title: str = ""
    extra: dict = field(default_factory=dict)

    @classmethod
    def from_frontmatter(cls, raw: dict) -> ChunkMetadata:
        tags = raw.get("tags", [])
        if isinstance(tags, str):
            tags = [t.strip() for t in tags.split(",") if t.strip()]
        elif not isinstance(tags, list):
            tags = []
        return cls(
            tags=tags,
            date=str(raw.get("date", "")),
            source=str(raw.get("source", "")),
            status=str(raw.get("status", "")),
            title=str(raw.get("title", "")),
            extra={
                k: v
                for k, v in raw.items()
                if k not in ("tags", "date", "source", "status", "title")
            },
        )


@dataclass
class Chunk:
    """一个知识块。"""

    source_file: str
    heading: str
    content: str
    metadata: ChunkMetadata
    start_line: int = 0

    @property
    def chunk_id(self) -> str:
        raw = (
            f"{self.source_file}:{self.start_line}:{self.heading}:{self.content[:100]}"
        )
        return hashlib.md5(raw.encode()).hexdigest()

    def to_store_metadata(self) -> dict:
        return {
            "source": self.source_file,
            "heading": self.heading,
            "tags": ",".join(self.metadata.tags),
            "date": self.metadata.date,
            "status": self.metadata.status,
            "title": self.metadata.title,
        }


@dataclass
class SearchResult:
    """搜索结果。"""

    source: str
    heading: str
    content: str
    score: float
    tags: str = ""
    date: str = ""
    title: str = ""


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
            f"  文件: {self.files_indexed} 已索引, "
            f"{self.files_skipped} 已跳过, "
            f"{self.files_removed} 已删除"
        )
        parts.append(f"  Chunks: {self.total_chunks}")
        return "\n".join(parts)


# ---------------------------------------------------------------------------
# Markdown 切分
# ---------------------------------------------------------------------------


def _parse_frontmatter(text: str) -> tuple[dict, str]:
    """解析 YAML frontmatter，返回 (metadata_dict, body)。"""
    if text.startswith("---"):
        parts = text.split("---", 2)
        if len(parts) >= 3:
            try:
                meta = yaml.safe_load(parts[1]) or {}
                return meta, parts[2].strip()
            except yaml.YAMLError:
                pass
    return {}, text


def _split_by_headings(
    file_path: Path,
    docs_dir: Path,
    min_chunk_length: int = 20,
) -> list[Chunk]:
    """按标题切分 Markdown 文件为 Chunk 列表。"""
    try:
        text = file_path.read_text(encoding="utf-8")
    except (UnicodeDecodeError, OSError):
        return []

    rel_path = str(file_path.relative_to(docs_dir))
    raw_meta, body = _parse_frontmatter(text)
    metadata = ChunkMetadata.from_frontmatter(raw_meta)

    chunks: list[Chunk] = []
    current_lines: list[str] = []
    heading_stack: list[str] = [rel_path]
    current_start_line = 1

    if text.startswith("---"):
        pre_body = text[: text.index(body)] if body and body in text else ""
        body_offset = pre_body.count("\n")
    else:
        body_offset = 0

    lines = body.split("\n")
    for i, line in enumerate(lines):
        m = re.match(r"^(#{1,3})\s+(.+)$", line)
        if m:
            if current_lines:
                content = "\n".join(current_lines).strip()
                if len(content) >= min_chunk_length:
                    chunks.append(
                        Chunk(
                            source_file=rel_path,
                            heading=" > ".join(heading_stack),
                            content=content,
                            metadata=metadata,
                            start_line=current_start_line + body_offset,
                        )
                    )
            level = len(m.group(1))
            title = m.group(2).strip()
            heading_stack = heading_stack[:1]
            if level >= 2:
                heading_stack.append(title)
            current_lines = [line]
            current_start_line = i + 1
        else:
            current_lines.append(line)

    if current_lines:
        content = "\n".join(current_lines).strip()
        if len(content) >= min_chunk_length:
            chunks.append(
                Chunk(
                    source_file=rel_path,
                    heading=" > ".join(heading_stack),
                    content=content,
                    metadata=metadata,
                    start_line=current_start_line + body_offset,
                )
            )

    if not chunks and len(body.strip()) >= min_chunk_length:
        chunks.append(
            Chunk(
                source_file=rel_path,
                heading=rel_path,
                content=body.strip(),
                metadata=metadata,
                start_line=1 + body_offset,
            )
        )

    return chunks


# ---------------------------------------------------------------------------
# 索引元数据（用于增量更新）
# ---------------------------------------------------------------------------

_INDEX_META_FILE = ".index_meta.json"


def _load_index_meta(chroma_dir: Path) -> dict[str, float]:
    meta_path = chroma_dir / _INDEX_META_FILE
    if meta_path.exists():
        try:
            return json.loads(meta_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            pass
    return {}


def _save_index_meta(chroma_dir: Path, meta: dict[str, float]) -> None:
    meta_path = chroma_dir / _INDEX_META_FILE
    meta_path.parent.mkdir(parents=True, exist_ok=True)
    meta_path.write_text(
        json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8"
    )


# ---------------------------------------------------------------------------
# VectorIndex — 统一接口
# ---------------------------------------------------------------------------


class VectorIndex:
    """向量索引 — 切分、存储、搜索、增量更新一体化。

    使用 ChromaDB 内置 all-MiniLM-L6-v2 做 embedding，完全本地运行。
    """

    def __init__(self, config: Config):
        self.config = config
        self._client: chromadb.PersistentClient | None = None
        self._collection: chromadb.Collection | None = None

    @property
    def collection(self) -> chromadb.Collection:
        """懒初始化 ChromaDB collection。"""
        if self._collection is None:
            self.config.chroma_dir.mkdir(parents=True, exist_ok=True)
            self._client = chromadb.PersistentClient(path=str(self.config.chroma_dir))
            self._collection = self._client.get_or_create_collection(
                name=self.config.collection_name,
                metadata={"hnsw:space": "cosine"},
            )
        return self._collection

    # ── 搜索 ──

    def search(
        self,
        query: str,
        top_k: int = 5,
        tags: list[str] | None = None,
    ) -> list[SearchResult]:
        """语义搜索。

        Args:
            query: 搜索查询文本
            top_k: 返回结果数
            tags: 可选的 tag 过滤列表

        Returns:
            SearchResult 列表，按相关度降序
        """
        if self.count() == 0:
            return []

        n = min(top_k, self.count())
        where = None
        if tags and len(tags) == 1:
            where = {"tags": {"$contains": tags[0]}}

        query_n = n if not tags or len(tags) == 1 else min(n * 5, self.count())

        results = self.collection.query(
            query_texts=[query],
            n_results=query_n,
            where=where,
        )

        if not results["documents"] or not results["documents"][0]:
            return []

        hits: list[SearchResult] = []
        for i in range(len(results["documents"][0])):
            distance = results["distances"][0][i] if results["distances"] else 0
            meta = results["metadatas"][0][i] if results["metadatas"] else {}
            hits.append(
                SearchResult(
                    source=meta.get("source", ""),
                    heading=meta.get("heading", ""),
                    content=results["documents"][0][i],
                    score=1 - distance,
                    tags=meta.get("tags", ""),
                    date=meta.get("date", ""),
                    title=meta.get("title", ""),
                )
            )

        if tags and len(tags) > 1:
            hits = [h for h in hits if any(t in h.tags for t in tags)][:top_k]

        return hits

    # ── 索引操作 ──

    def build(self, force: bool = False) -> IndexStats:
        """构建索引（增量或全量）。

        Args:
            force: True = 全量重建，False = 增量更新
        """
        start = time.time()
        stats = IndexStats()
        docs = self.config.docs_dir

        md_files: list[Path] = []
        if docs.exists():
            for md_file in docs.rglob("*.md"):
                if any(part in self.config.skip_dirs for part in md_file.parts):
                    continue
                md_files.append(md_file)

        stats.total_files = len(md_files)

        if force:
            self._clear()
            index_meta: dict[str, float] = {}
        else:
            index_meta = _load_index_meta(self.config.chroma_dir)

        all_current_sources: set[str] = set()
        for md_file in md_files:
            rel_path = str(md_file.relative_to(docs))
            all_current_sources.add(rel_path)
            file_mtime = md_file.stat().st_mtime

            if not force and rel_path in index_meta:
                if index_meta[rel_path] >= file_mtime:
                    stats.files_skipped += 1
                    continue

            self._delete_by_file(rel_path)
            chunks = _split_by_headings(md_file, docs, self.config.min_chunk_length)
            if chunks:
                self._upsert_chunks(chunks)

            stats.files_indexed += 1
            stats.total_chunks += len(chunks)
            index_meta[rel_path] = file_mtime

        removed_sources = set(index_meta.keys()) - all_current_sources
        for src in removed_sources:
            self._delete_by_file(src)
            del index_meta[src]
            stats.files_removed += 1

        _save_index_meta(self.config.chroma_dir, index_meta)

        stats.total_chunks = self.count()
        stats.duration_seconds = time.time() - start
        return stats

    def refresh(self) -> IndexStats:
        """增量更新索引。"""
        return self.build(force=False)

    def index_file(self, file_path: Path) -> int:
        """索引单个文件，返回 chunk 数量。"""
        docs = self.config.docs_dir
        rel_path = str(file_path.relative_to(docs))

        self._delete_by_file(rel_path)
        chunks = _split_by_headings(file_path, docs, self.config.min_chunk_length)
        if chunks:
            self._upsert_chunks(chunks)

        index_meta = _load_index_meta(self.config.chroma_dir)
        index_meta[rel_path] = file_path.stat().st_mtime
        _save_index_meta(self.config.chroma_dir, index_meta)

        return len(chunks)

    # ── 统计 ──

    def count(self) -> int:
        """当前索引中的 chunk 数量。"""
        return self.collection.count()

    def get_all_sources(self) -> list[dict]:
        """获取所有已索引文件的信息。"""
        if self.count() == 0:
            return []

        all_data = self.collection.get(include=["metadatas"])
        source_info: dict[str, dict] = {}
        for meta in all_data["metadatas"]:
            if not meta:
                continue
            src = meta.get("source", "")
            if src not in source_info:
                source_info[src] = {
                    "source": src,
                    "chunk_count": 0,
                    "tags": set(),
                    "title": meta.get("title", ""),
                }
            source_info[src]["chunk_count"] += 1
            tags_str = meta.get("tags", "")
            if tags_str:
                source_info[src]["tags"].update(
                    t.strip() for t in tags_str.split(",") if t.strip()
                )

        result = []
        for info in sorted(source_info.values(), key=lambda x: x["source"]):
            info["tags"] = ",".join(sorted(info["tags"]))
            result.append(info)
        return result

    # ── 内部方法 ──

    def _upsert_chunks(self, chunks: list[Chunk]) -> int:
        if not chunks:
            return 0
        # 去重：同一 chunk_id 只保留最后一个
        seen: dict[str, Chunk] = {}
        for c in chunks:
            seen[c.chunk_id] = c
        deduped = list(seen.values())

        total = 0
        batch_size = self.config.batch_size
        max_len = self.config.max_chunk_store_length
        for i in range(0, len(deduped), batch_size):
            batch = deduped[i : i + batch_size]
            self.collection.upsert(
                ids=[c.chunk_id for c in batch],
                documents=[c.content[:max_len] for c in batch],
                metadatas=[c.to_store_metadata() for c in batch],
            )
            total += len(batch)
        return total

    def _delete_by_file(self, source_file: str) -> int:
        results = self.collection.get(where={"source": source_file})
        if not results["ids"]:
            return 0
        count = len(results["ids"])
        self.collection.delete(ids=results["ids"])
        return count

    def _clear(self) -> int:
        count = self.count()
        if count > 0:
            all_ids = self.collection.get()["ids"]
            if all_ids:
                self.collection.delete(ids=all_ids)
        return count
