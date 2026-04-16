"""
Resources — 生成资源总览页面。

按来源类型分组展示所有文章，支持表格、统计和筛选。
"""

from __future__ import annotations

import re
from pathlib import Path


def _extract_frontmatter(md_file: Path) -> dict:
    """从 Markdown 文件提取 frontmatter 字段。"""
    text = md_file.read_text(encoding="utf-8")
    if not text.startswith("---"):
        return {"title": md_file.stem}

    parts = text.split("---", 2)
    if len(parts) < 3:
        return {"title": md_file.stem}

    meta = {}
    for line in parts[1].strip().split("\n"):
        if ":" in line:
            key, _, val = line.partition(":")
            meta[key.strip()] = val.strip().strip('"').strip("'")

    # 解析 tags
    tags_str = meta.get("tags", "")
    if tags_str.startswith("[") and tags_str.endswith("]"):
        meta["tags_list"] = [t.strip() for t in tags_str[1:-1].split(",")]
    else:
        meta["tags_list"] = []

    if "title" not in meta:
        meta["title"] = md_file.stem.replace("-", " ").title()

    return meta


def _detect_source_type(meta: dict) -> str:
    """根据 tags 和 source 判断来源类型。"""
    tags = meta.get("tags_list", [])
    source = meta.get("source", "")

    if "video" in tags or "douyin" in tags or "bilibili" in tags or "youtube" in tags:
        return "video"
    if "pdf" in tags:
        return "pdf"
    if "web-clip" in tags:
        return "web"
    if source.startswith("http"):
        return "web"
    return "other"


def _source_type_label(t: str) -> str:
    return {
        "video": "视频",
        "pdf": "PDF 文档",
        "web": "网页文章",
        "other": "其他",
    }.get(t, t)


def _source_type_icon(t: str) -> str:
    return {
        "video": "🎬",
        "pdf": "📄",
        "web": "🌐",
        "other": "📝",
    }.get(t, "📝")


def generate_resources_page(docs_dir: Path) -> bool:
    """生成资源总览页面 wiki/resources.md。"""
    articles_dir = docs_dir / "wiki" / "articles"
    if not articles_dir.exists():
        return False

    # 收集所有文章信息
    articles = []
    for md in sorted(articles_dir.rglob("*.md")):
        if md.name == "index.md":
            continue
        meta = _extract_frontmatter(md)
        rel_path = str(md.relative_to(docs_dir))
        source_type = _detect_source_type(meta)

        articles.append(
            {
                "title": meta.get("title", md.stem),
                "source_type": source_type,
                "tags": meta.get("tags_list", []),
                "source": meta.get("source", ""),
                "created": meta.get("created", ""),
                "status": meta.get("status", ""),
                "path": rel_path,
                "url": rel_path.replace(".md", "/"),
            }
        )

    if not articles:
        return False

    # 按类型分组
    groups: dict[str, list] = {}
    for a in articles:
        groups.setdefault(a["source_type"], []).append(a)

    # 统计
    total = len(articles)
    type_counts = {k: len(v) for k, v in groups.items()}

    # 生成页面
    lines = [
        "---",
        "hide:",
        "  - navigation",
        "---",
        "",
        "# 资源总览",
        "",
    ]

    # 统计卡片
    lines.append('<div class="resource-stats">')
    lines.append(
        f'  <div class="stat-card stat-total"><div class="stat-num">{total}</div><div class="stat-label">总计</div></div>'
    )
    for t in ["video", "pdf", "web", "other"]:
        if t in type_counts:
            icon = _source_type_icon(t)
            label = _source_type_label(t)
            lines.append(
                f'  <div class="stat-card"><div class="stat-num">{icon} {type_counts[t]}</div><div class="stat-label">{label}</div></div>'
            )
    lines.append("</div>")
    lines.append("")

    # CSS
    lines.append("<style>")
    lines.append(
        ".resource-stats { display: flex; gap: 12px; margin: 1em 0 2em; flex-wrap: wrap; }"
    )
    lines.append(
        ".stat-card { background: #f8f9fa; border: 1px solid #e0e0e0; border-radius: 8px; padding: 12px 20px; text-align: center; min-width: 80px; }"
    )
    lines.append(
        ".stat-card.stat-total { background: #4a9eff; color: #fff; border-color: #2b7de9; }"
    )
    lines.append(".stat-num { font-size: 20px; font-weight: bold; }")
    lines.append(".stat-label { font-size: 12px; color: #888; margin-top: 4px; }")
    lines.append(".stat-card.stat-total .stat-label { color: rgba(255,255,255,0.8); }")
    lines.append(
        ".resource-table { width: 100%; border-collapse: collapse; margin: 1em 0; }"
    )
    lines.append(
        ".resource-table th { background: #f5f5f5; padding: 8px 12px; text-align: left; font-size: 13px; border-bottom: 2px solid #ddd; }"
    )
    lines.append(
        ".resource-table td { padding: 8px 12px; border-bottom: 1px solid #eee; font-size: 13px; }"
    )
    lines.append(".resource-table tr:hover { background: #f8f9fa; }")
    lines.append(
        ".status-badge { display: inline-block; padding: 2px 8px; border-radius: 10px; font-size: 11px; }"
    )
    lines.append(".status-seedling { background: #fef3c7; color: #92400e; }")
    lines.append(".status-developing { background: #dbeafe; color: #1e40af; }")
    lines.append(".status-published { background: #d1fae5; color: #065f46; }")
    lines.append("</style>")
    lines.append("")

    # 按类型输出表格
    type_order = ["video", "pdf", "web", "other"]
    for t in type_order:
        items = groups.get(t)
        if not items:
            continue

        icon = _source_type_icon(t)
        label = _source_type_label(t)
        lines.append(f"## {icon} {label} ({len(items)})")
        lines.append("")
        lines.append('<table class="resource-table">')
        lines.append("  <tr><th>标题</th><th>日期</th><th>状态</th><th>标签</th></tr>")

        for item in sorted(items, key=lambda x: x.get("created", ""), reverse=True):
            title = item["title"]
            url = item["url"]
            created = item.get("created", "—")
            status = item.get("status", "")
            tags = ", ".join(
                t for t in item.get("tags", []) if t not in ("video", "pdf", "web-clip")
            )

            # 状态徽章
            status_class = (
                f"status-{status}"
                if status in ("seedling", "developing", "published")
                else ""
            )
            status_html = (
                f'<span class="status-badge {status_class}">{status}</span>'
                if status
                else "—"
            )

            title_link = f'<a href="/{url}">{title}</a>'
            lines.append(
                f"  <tr><td>{title_link}</td><td>{created}</td><td>{status_html}</td><td>{tags}</td></tr>"
            )

        lines.append("</table>")
        lines.append("")

    wiki_dir = docs_dir / "wiki"
    wiki_dir.mkdir(parents=True, exist_ok=True)
    (wiki_dir / "resources.md").write_text("\n".join(lines), encoding="utf-8")
    return True
