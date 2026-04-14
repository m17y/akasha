"""
向量存储 — ChromaDB 封装。

职责:
- 管理 ChromaDB PersistentClient 和 collection
- upsert / search / delete 操作
- 搜索支持 tags 过滤（ChromaDB where 子句）
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import chromadb

from .chunker import Chunk


# ---------------------------------------------------------------------------
# 数据结构
# ---------------------------------------------------------------------------


@dataclass
class SearchResult:
    """搜索结果。"""

    source: str
    heading: str
    content: str
    score: float  # 相似度 0~1 (1 - cosine distance)
    tags: str = ""
    date: str = ""
    title: str = ""


# ---------------------------------------------------------------------------
# VectorStore
# ---------------------------------------------------------------------------


class VectorStore:
    """ChromaDB 向量存储封装。

    使用 ChromaDB 内置的 all-MiniLM-L6-v2 模型做 embedding，
    完全本地运行，不需要 API Key。
    """

    def __init__(
        self,
        chroma_dir: Path,
        collection_name: str = "knowledge",
    ):
        self._chroma_dir = chroma_dir
        self._collection_name = collection_name
        self._client: chromadb.PersistentClient | None = None
        self._collection: chromadb.Collection | None = None

    @property
    def collection(self) -> chromadb.Collection:
        """懒初始化 collection。"""
        if self._collection is None:
            self._chroma_dir.mkdir(parents=True, exist_ok=True)
            self._client = chromadb.PersistentClient(path=str(self._chroma_dir))
            self._collection = self._client.get_or_create_collection(
                name=self._collection_name,
                metadata={"hnsw:space": "cosine"},
            )
        return self._collection

    def count(self) -> int:
        """返回当前索引中的 chunk 数量。"""
        return self.collection.count()

    def upsert_chunks(
        self,
        chunks: list[Chunk],
        batch_size: int = 100,
        max_content_length: int = 8000,
    ) -> int:
        """批量写入 chunks。ChromaDB 自动生成 embedding。

        Args:
            chunks: Chunk 列表
            batch_size: 每批写入数量
            max_content_length: 内容截断长度

        Returns:
            写入的 chunk 数量
        """
        if not chunks:
            return 0

        total = 0
        for i in range(0, len(chunks), batch_size):
            batch = chunks[i : i + batch_size]
            ids = [c.chunk_id for c in batch]
            documents = [c.content[:max_content_length] for c in batch]
            metadatas = [c.to_store_metadata() for c in batch]

            self.collection.upsert(
                ids=ids,
                documents=documents,
                metadatas=metadatas,
            )
            total += len(batch)

        return total

    def search(
        self,
        query: str,
        top_k: int = 5,
        tags: list[str] | None = None,
    ) -> list[SearchResult]:
        """语义搜索。

        Args:
            query: 搜索查询文本
            top_k: 返回最相关的结果数
            tags: 可选的 tag 过滤列表（任一匹配即可）

        Returns:
            SearchResult 列表，按相关度降序
        """
        if self.count() == 0:
            return []

        n = min(top_k, self.count())

        # 构建 where 子句（tag 过滤）
        # ChromaDB $contains 用于字符串子串匹配
        # 多 tag 用 $or 时需要 where_document 或分别查询后合并
        # ChromaDB 对 $or + $contains 支持有限，改用单个查询 + 后过滤
        where = None
        if tags and len(tags) == 1:
            where = {"tags": {"$contains": tags[0]}}

        # 多 tag 时: 查更多结果，再 post-filter
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

        # 多 tag post-filter: 保留包含任一指定 tag 的结果
        if tags and len(tags) > 1:
            hits = [h for h in hits if any(t in h.tags for t in tags)][:top_k]

        return hits

    def delete_by_file(self, source_file: str) -> int:
        """删除指定文件的所有 chunks。

        Args:
            source_file: 相对路径（与 Chunk.source_file 一致）

        Returns:
            删除的 chunk 数量
        """
        # 先查出该文件的所有 chunk IDs
        results = self.collection.get(
            where={"source": source_file},
        )
        if not results["ids"]:
            return 0

        count = len(results["ids"])
        self.collection.delete(ids=results["ids"])
        return count

    def clear(self) -> int:
        """清空所有数据。

        Returns:
            清除的 chunk 数量
        """
        count = self.count()
        if count > 0:
            all_ids = self.collection.get()["ids"]
            if all_ids:
                self.collection.delete(ids=all_ids)
        return count

    def get_all_sources(self) -> list[dict]:
        """获取所有已索引文件的信息。

        Returns:
            [{"source": "path", "chunk_count": N, "tags": "..."}, ...]
        """
        if self.count() == 0:
            return []

        all_data = self.collection.get(include=["metadatas"])
        # 按 source 聚合
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

        # 转换 tags set → 逗号字符串
        result = []
        for info in sorted(source_info.values(), key=lambda x: x["source"]):
            info["tags"] = ",".join(sorted(info["tags"]))
            result.append(info)
        return result
