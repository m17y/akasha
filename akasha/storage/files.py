"""
文件存储 — 知识库文件系统操作。

职责:
- 读取笔记（支持分页）
- 写入 wiki 页面（仅限 wiki/ 目录）
- 列出文件
- 路径安全校验（防穿越、防写 raw/）
- vault 目录结构初始化
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from ..config import Config


# ---------------------------------------------------------------------------
# 数据结构
# ---------------------------------------------------------------------------


@dataclass
class ReadResult:
    """文件读取结果。"""

    content: str
    total_length: int
    truncated: bool = False
    next_offset: int = 0


# ---------------------------------------------------------------------------
# FileStore
# ---------------------------------------------------------------------------


class FileStore:
    """知识库文件系统操作。"""

    def __init__(self, config: Config):
        self.config = config

    # ── 读取 ──

    def read(self, file_path: str, offset: int = 0) -> ReadResult:
        """读取笔记内容，支持分页。

        Args:
            file_path: 相对于 docs 目录的路径
            offset: 从第几个字符开始读取

        Returns:
            ReadResult

        Raises:
            ValueError: 路径不合法
            FileNotFoundError: 文件不存在
        """
        self._validate_read_path(file_path)

        full_path = self.config.docs_dir / file_path
        if not full_path.exists():
            raise FileNotFoundError(f"文件不存在: {file_path}")
        if not full_path.is_file():
            raise ValueError(f"不是文件: {file_path}")

        content = full_path.read_text(encoding="utf-8")
        total = len(content)

        if offset > 0:
            content = content[offset:]

        if len(content) > self.config.max_read_length:
            return ReadResult(
                content=content[: self.config.max_read_length],
                total_length=total,
                truncated=True,
                next_offset=offset + self.config.max_read_length,
            )

        return ReadResult(content=content, total_length=total)

    def read_raw(self, file_path: str) -> str:
        """读取文件完整内容（无分页，内部使用）。

        Args:
            file_path: 相对于 docs 目录的路径

        Returns:
            文件完整内容
        """
        full_path = self.config.docs_dir / file_path
        if not full_path.exists():
            raise FileNotFoundError(f"文件不存在: {file_path}")
        return full_path.read_text(encoding="utf-8")

    # ── 写入 ──

    def write_wiki(self, page_path: str, content: str) -> Path:
        """写入 wiki 页面（仅限 wiki/ 目录）。

        Args:
            page_path: 相对于 docs 目录的路径（如 wiki/concepts/xxx.md）
            content: 页面内容

        Returns:
            写入的文件完整路径

        Raises:
            ValueError: 路径不合法（不在 wiki/ 下或路径穿越）
        """
        self._validate_write_path(page_path)

        full_path = self.config.docs_dir / page_path
        full_path.parent.mkdir(parents=True, exist_ok=True)
        full_path.write_text(content, encoding="utf-8")
        return full_path

    def append_file(self, file_path: str, content: str) -> None:
        """追加内容到文件（用于 log.md 等）。文件不存在则创建。"""
        full_path = self.config.docs_dir / file_path
        full_path.parent.mkdir(parents=True, exist_ok=True)
        if full_path.exists():
            existing = full_path.read_text(encoding="utf-8")
            full_path.write_text(existing + content, encoding="utf-8")
        else:
            full_path.write_text(
                f"# 操作日志\n\n> Append-only. 每次操作自动追加。\n{content}",
                encoding="utf-8",
            )

    # ── 列出 ──

    def list_files(self, subdir: str = "") -> list[str]:
        """列出 docs 下的 .md 文件。

        Args:
            subdir: 子目录过滤（如 "raw"、"wiki"），空字符串则列出所有

        Returns:
            相对于 docs 的文件路径列表
        """
        base = self.config.docs_dir / subdir if subdir else self.config.docs_dir
        if not base.exists():
            return []

        files = []
        for md_file in sorted(base.rglob("*.md")):
            if any(part in self.config.skip_dirs for part in md_file.parts):
                continue
            files.append(str(md_file.relative_to(self.config.docs_dir)))
        return files

    def list_wiki_pages(self) -> list[str]:
        """列出所有 wiki 页面路径。"""
        return self.list_files("wiki")

    # ── 初始化 ──

    def init_vault(self) -> None:
        """初始化 vault 目录结构。"""
        vault = self.config.vault_path
        docs = self.config.docs_dir

        vault.mkdir(parents=True, exist_ok=True)
        docs.mkdir(parents=True, exist_ok=True)
        self.config.site_dir.mkdir(parents=True, exist_ok=True)

        for subdir in [
            "raw/analysis",
            "raw/notes",
            "raw/articles",
            "wiki/concepts",
            "wiki/entities",
            "wiki/comparisons",
            "wiki/synthesis",
            "assets/video",
        ]:
            (docs / subdir).mkdir(parents=True, exist_ok=True)

        if not self.config.schema_path.exists():
            self.config.schema_path.write_text(
                "# Knowledge Wiki Schema\n\n"
                "> 本文件定义 wiki 规则。详见 DESIGN.md。\n\n"
                "将你的自定义 schema 规则写在这里。\n",
                encoding="utf-8",
            )

        if not self.config.index_path.exists():
            self.config.index_path.write_text(
                "# 知识库目录\n\n"
                "> 自动维护，每次 ingest 或 save_as_page 后更新。\n\n---\n\n"
                "## 概念 (concepts/)\n\n*暂无条目 — 执行 ingest 后自动生成。*\n\n"
                "## 实体 (entities/)\n\n*暂无条目 — 执行 ingest 后自动生成。*\n\n"
                "## 对比 (comparisons/)\n\n*暂无条目 — 执行 ingest 后自动生成。*\n\n"
                "## 综合 (synthesis/)\n\n*暂无条目 — 执行 save_as_page 后自动生成。*\n",
                encoding="utf-8",
            )

        if not self.config.log_path.exists():
            self.config.log_path.write_text(
                "# 知识库日志\n\n"
                "> Append-only. 每次 ingest / save_as_page 自动追加。\n\n---\n",
                encoding="utf-8",
            )

    # ── 安全校验 ──

    def _validate_read_path(self, file_path: str) -> None:
        """校验读取路径合法性。"""
        if ".." in file_path:
            raise ValueError(f"路径不合法（包含 ..）: {file_path}")

        full_path = (self.config.docs_dir / file_path).resolve()
        docs_resolved = self.config.docs_dir.resolve()

        if (
            not str(full_path).startswith(str(docs_resolved) + os.sep)
            and full_path != docs_resolved
        ):
            raise ValueError(f"路径不在 docs 范围内: {file_path}")

    def _validate_write_path(self, page_path: str) -> None:
        """校验写入路径合法性（只允许写 wiki/）。"""
        if ".." in page_path:
            raise ValueError(f"路径不合法（包含 ..）: {page_path}")

        if not page_path.startswith("wiki/"):
            raise ValueError(f"只允许写入 wiki/ 目录: {page_path}")

        full_path = (self.config.docs_dir / page_path).resolve()
        wiki_resolved = self.config.wiki_dir.resolve()

        if (
            not str(full_path).startswith(str(wiki_resolved) + "/")
            and full_path != wiki_resolved
        ):
            raise ValueError(f"路径逃逸出 wiki 目录: {page_path}")
