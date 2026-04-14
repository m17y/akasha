"""
Markdown 切分器 — 按标题层级切分 Markdown 文件为 chunks。

规则:
- 以 # / ## / ### 为切分点
- 每个 chunk 保留标题层级路径（如 "hive.md > 窗口函数"）
- 过短的 chunk（< min_chunk_length）被跳过
- 解析 YAML frontmatter 提取 tags / date / source / status
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from pathlib import Path

import yaml


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
    def from_frontmatter(cls, raw: dict) -> "ChunkMetadata":
        """从 frontmatter dict 构造。"""
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

    source_file: str  # 相对于 vault 的路径
    heading: str  # 标题层级路径
    content: str  # 文本内容
    metadata: ChunkMetadata  # 结构化元数据
    start_line: int = 0  # 在原文件中的起始行号

    @property
    def chunk_id(self) -> str:
        """确定性唯一 ID（MD5）。"""
        raw = f"{self.source_file}:{self.heading}:{self.content[:100]}"
        return hashlib.md5(raw.encode()).hexdigest()

    def to_store_metadata(self) -> dict:
        """转换为 ChromaDB metadata 格式（只支持 str/int/float/bool）。"""
        return {
            "source": self.source_file,
            "heading": self.heading,
            "tags": ",".join(self.metadata.tags),
            "date": self.metadata.date,
            "status": self.metadata.status,
            "title": self.metadata.title,
        }


# ---------------------------------------------------------------------------
# 解析
# ---------------------------------------------------------------------------


def parse_frontmatter(text: str) -> tuple[dict, str]:
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


def split_by_headings(
    file_path: Path,
    vault_root: Path,
    min_chunk_length: int = 20,
) -> list[Chunk]:
    """按标题切分 Markdown 文件为 Chunk 列表。

    Args:
        file_path: 文件绝对路径
        vault_root: vault 根目录
        min_chunk_length: chunk 最小字符数（低于此值跳过）

    Returns:
        Chunk 列表
    """
    try:
        text = file_path.read_text(encoding="utf-8")
    except (UnicodeDecodeError, OSError):
        return []

    rel_path = str(file_path.relative_to(vault_root))
    raw_meta, body = parse_frontmatter(text)
    metadata = ChunkMetadata.from_frontmatter(raw_meta)

    chunks: list[Chunk] = []
    current_lines: list[str] = []
    heading_stack: list[str] = [rel_path]
    current_start_line = 1

    # 计算 body 在原文件中的起始行号
    if text.startswith("---"):
        # frontmatter 占的行数
        pre_body = text[: text.index(body)] if body and body in text else ""
        body_offset = pre_body.count("\n")
    else:
        body_offset = 0

    lines = body.split("\n")
    for i, line in enumerate(lines):
        m = re.match(r"^(#{1,3})\s+(.+)$", line)
        if m:
            # 保存之前的 chunk
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

            # 更新标题栈
            level = len(m.group(1))
            title = m.group(2).strip()
            heading_stack = heading_stack[:1]  # 保留文件名
            if level >= 2:
                heading_stack.append(title)
            current_lines = [line]
            current_start_line = i + 1
        else:
            current_lines.append(line)

    # 最后一个 chunk
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

    # 如果整个文件没有标题，作为一个 chunk
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


def scan_vault(
    vault_path: Path,
    skip_dirs: set[str] | None = None,
    min_chunk_length: int = 20,
) -> list[Chunk]:
    """扫描 vault 下所有 .md 文件，返回所有 chunks。

    Args:
        vault_path: vault 根目录
        skip_dirs: 要跳过的目录名集合
        min_chunk_length: chunk 最小字符数
    """
    if skip_dirs is None:
        skip_dirs = {
            ".obsidian",
            ".git",
            "node_modules",
            "__pycache__",
            "site",
            ".venv",
        }

    all_chunks: list[Chunk] = []
    for md_file in vault_path.rglob("*.md"):
        if any(part in skip_dirs for part in md_file.parts):
            continue
        chunks = split_by_headings(md_file, vault_path, min_chunk_length)
        all_chunks.extend(chunks)
    return all_chunks
