"""[[双链]] 渲染。"""

from __future__ import annotations

import os
from pathlib import Path

from .mkdocs_config import _extract_title


def _build_wikilink_map(docs_dir: Path) -> dict[str, str]:
    """扫描 wiki/ 下所有页面，建立 标题/文件名 → 相对路径 的映射。"""
    link_map: dict[str, str] = {}
    wiki_dir = docs_dir / "wiki"
    if not wiki_dir.exists():
        return link_map

    for md_file in wiki_dir.rglob("*.md"):
        rel_path = str(md_file.relative_to(docs_dir))
        # 文件名（不含扩展名）作为 key
        stem = md_file.stem
        link_map[stem] = rel_path
        link_map[stem.lower()] = rel_path
        # frontmatter title 也作为 key
        title = _extract_title(md_file)
        if title and title != stem:
            link_map[title] = rel_path
            link_map[title.lower()] = rel_path

    return link_map


def _resolve_wikilinks(docs_dir: Path, link_map: dict[str, str]) -> int:
    """把 docs/ 下所有 md 文件中的 [[xxx]] 替换为 [xxx](实际路径)。

    注意：不修改源文件，而是写到 _build/ 临时目录。mkdocs 构建时使用 _build/ 作为 docs_dir。
    如果没有 [[双链]]，则不复制文件（节省磁盘）。
    """
    import re
    import shutil

    total_replaced = 0
    wiki_dir = docs_dir / "wiki"
    if not wiki_dir.exists():
        return 0

    # 创建构建用的临时目录（与 docs 平级）
    build_dir = docs_dir.parent / "_build_docs"
    # 每次全量复制源文件到 build 目录
    if build_dir.exists():
        shutil.rmtree(build_dir)
    shutil.copytree(docs_dir, build_dir)

    build_wiki_dir = build_dir / "wiki"
    for md_file in build_wiki_dir.rglob("*.md"):
        text = md_file.read_text(encoding="utf-8")
        file_dir = md_file.parent

        def _replace(m):
            nonlocal total_replaced
            name = m.group(1).strip()
            # 查找映射
            target = link_map.get(name) or link_map.get(name.lower())
            if target:
                # 计算从当前文件到目标的相对路径
                target_path = build_dir / target
                try:
                    rel = os.path.relpath(target_path, file_dir)
                except ValueError:
                    rel = target
                total_replaced += 1
                return f"[{name}]({rel})"
            # 找不到目标，保留 [[双链]] 原样
            return m.group(0)

        new_text = re.sub(r"\[\[([^\]]+)\]\]", _replace, text)
        if new_text != text:
            md_file.write_text(new_text, encoding="utf-8")

    return total_replaced
