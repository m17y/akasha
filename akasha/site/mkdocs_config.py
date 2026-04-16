"""mkdocs 配置生成 + 导航扫描。"""

from __future__ import annotations

from pathlib import Path


def _generate_mkdocs_config(cfg) -> dict:
    """根据 vault 结构动态生成 mkdocs 配置。"""
    return {
        "site_name": "Akasha",
        "site_description": "个人知识库 — 语义搜索 + LLM Wiki 知识编译",
        "docs_dir": str(cfg.docs_dir),
        "site_dir": str(cfg.site_dir),
        "theme": {
            "name": "material",
            "language": "zh",
            "palette": [
                # 亮色模式 — 参考 OI-wiki: 白底 + 红色强调
                {
                    "media": "(prefers-color-scheme: light)",
                    "scheme": "default",
                    "primary": "white",
                    "accent": "red",
                    "toggle": {
                        "icon": "material/weather-sunny",
                        "name": "切换到暗色模式",
                    },
                },
                # 暗色模式 — 蓝底 + 蓝色强调
                {
                    "media": "(prefers-color-scheme: dark)",
                    "scheme": "slate",
                    "primary": "blue",
                    "accent": "blue",
                    "toggle": {
                        "icon": "material/weather-night",
                        "name": "切换到亮色模式",
                    },
                },
            ],
            "icon": {
                "logo": "material/book-open-page-variant",
            },
            "font": {
                "text": "Fira Sans",
                "code": "Fira Mono",
            },
            "features": [
                "navigation.tabs",
                "navigation.sections",
                "navigation.expand",
                "navigation.top",
                "navigation.instant",
                "search.suggest",
                "search.highlight",
                "content.code.copy",
            ],
        },
        "plugins": [
            {"search": {"lang": ["zh", "en"]}},
            "tags",
        ],
        "markdown_extensions": [
            "admonition",
            "attr_list",
            "md_in_html",
            "def_list",
            "footnotes",
            "tables",
            {"toc": {"permalink": True}},
            {"pymdownx.highlight": {"linenums": True}},
            "pymdownx.inlinehilite",
            {
                "pymdownx.superfences": {
                    "custom_fences": [
                        {
                            "name": "mermaid",
                            "class": "mermaid",
                            "format": "!!python/name:pymdownx.superfences.fence_code_format",
                        }
                    ]
                }
            },
            {"pymdownx.tabbed": {"alternate_style": True}},
            {"pymdownx.tasklist": {"custom_checkbox": True}},
            "pymdownx.details",
            "pymdownx.keys",
            "pymdownx.mark",
            "pymdownx.caret",
            "pymdownx.tilde",
            "pymdownx.smartsymbols",
        ],
        "nav": _build_nav(cfg.docs_dir),
    }


def _build_nav(docs_dir: Path) -> list:
    """扫描 docs 目录结构，生成 nav 导航。"""
    nav = []

    if (docs_dir / "index.md").exists():
        nav.append({"首页": "index.md"})

    # wiki 子目录各自作为顶级导航项
    wiki_dir = docs_dir / "wiki"
    if wiki_dir.exists():
        for cat_name, cat_label in _NAV_CATEGORIES.items():
            cat_dir = wiki_dir / cat_name
            if not cat_dir.exists():
                continue
            items = []
            for md in sorted(cat_dir.rglob("*.md")):
                rel = str(md.relative_to(docs_dir))
                name = _extract_title(md)
                items.append({name: rel})
            if items:
                nav.append({cat_label: items})

    # 知识图谱
    if (docs_dir / "wiki" / "graph.md").exists():
        nav.append({"图谱": "wiki/graph.md"})

    raw_section = _scan_section(docs_dir, "raw", "原始素材")
    if raw_section:
        nav.append(raw_section)

    if (docs_dir / "wiki" / "resources.md").exists():
        nav.append({"资源总览": "wiki/resources.md"})

    if (docs_dir / "schema.md").exists():
        nav.append({"Schema": "schema.md"})

    if (docs_dir / "log.md").exists():
        nav.append({"日志": "log.md"})

    return nav


# wiki 子目录 → 导航栏显示（顺序决定导航栏顺序）
_NAV_CATEGORIES = {
    "articles": "文章",
    "concepts": "概念",
    "entities": "实体",
    "synthesis": "综合",
    "comparisons": "对比",
}

# raw 子目录中文别名
_RAW_DIR_LABELS = {
    "analysis": "分析文档",
    "notes": "笔记",
    "articles": "文章",
}


def _extract_title(md_path: Path) -> str:
    """从 Markdown 文件提取标题。优先级: frontmatter title > 第一个 # 标题 > 文件名。"""
    try:
        text = md_path.read_text(encoding="utf-8")

        # 1. frontmatter title
        if text.startswith("---"):
            parts = text.split("---", 2)
            if len(parts) >= 3:
                for line in parts[1].strip().split("\n"):
                    line = line.strip()
                    if line.startswith("title:"):
                        title = line[6:].strip().strip('"').strip("'")
                        if title:
                            return title

        # 2. 第一个 # 标题
        for line in text.split("\n")[:20]:
            line = line.strip()
            if line.startswith("# ") and not line.startswith("##"):
                return line[2:].strip()

    except (UnicodeDecodeError, OSError):
        pass

    # 3. fallback: 文件名
    return md_path.stem.replace("-", " ").title()


def _scan_section(docs_dir: Path, subdir: str, label: str) -> dict | None:
    """扫描子目录，生成嵌套 nav。"""
    dir_path = docs_dir / subdir
    if not dir_path.exists():
        return None

    items = []
    for child in sorted(dir_path.iterdir()):
        if child.is_dir():
            sub_items = []
            for md in sorted(child.rglob("*.md")):
                rel = str(md.relative_to(docs_dir))
                name = _extract_title(md)
                sub_items.append({name: rel})
            if sub_items:
                dir_label = _RAW_DIR_LABELS.get(
                    child.name, _NAV_CATEGORIES.get(child.name, child.name)
                )
                items.append({dir_label: sub_items})
        elif child.suffix == ".md":
            rel = str(child.relative_to(docs_dir))
            name = _extract_title(child)
            items.append({name: rel})

    if not items:
        return None
    return {label: items}
