"""
mkdocs-material 站点生成器。

目录结构:
  ~/akasha/                    ← vault 根目录
  ├── mkdocs.yml               ← 动态生成
  ├── docs/                    ← Markdown 内容 (mkdocs docs_dir)
  └── site/                    ← 构建产物 (mkdocs site_dir)

用法:
  knowledge-site serve     # 本地预览 http://127.0.0.1:8000
  knowledge-site build     # 构建静态站点到 vault/site/
  knowledge-site deploy    # 发布到 GitHub Pages
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import yaml

from .config import load_config


# ---------------------------------------------------------------------------
# mkdocs 配置生成
# ---------------------------------------------------------------------------


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


# ---------------------------------------------------------------------------
# [[双链]] 渲染
# ---------------------------------------------------------------------------


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


# ---------------------------------------------------------------------------
# 知识图谱
# ---------------------------------------------------------------------------


def _generate_graph_page(docs_dir: Path, link_map: dict[str, str]) -> bool:
    """扫描所有 wiki 页面的 related/tags + [[双链]]，生成 mermaid 关联图谱页面。"""
    import hashlib
    import re

    wiki_dir = docs_dir / "wiki"
    if not wiki_dir.exists():
        return False

    # 收集节点和边
    # node: id → {name, category}
    nodes: dict[str, dict] = {}
    edges: list[tuple[str, str]] = []

    for md_file in wiki_dir.rglob("*.md"):
        if md_file.name == "graph.md":
            continue
        title = _extract_title(md_file)
        node_id = _safe_id(title)

        # 根据所在目录判断类型
        rel = str(md_file.relative_to(wiki_dir))
        if rel.startswith("concepts"):
            category = "concept"
        elif rel.startswith("entities"):
            category = "entity"
        elif rel.startswith("articles"):
            category = "article"
        else:
            category = "other"

        nodes[node_id] = {"name": title, "category": category}

        text = md_file.read_text(encoding="utf-8")

        # 从 frontmatter 提取 related
        if text.startswith("---"):
            parts = text.split("---", 2)
            if len(parts) >= 3:
                fm = parts[1]
                for line in fm.split("\n"):
                    line = line.strip()
                    if line.startswith("related:"):
                        related_str = line[8:].strip().strip("[]")
                        for item in related_str.split(","):
                            item = item.strip().strip('"').strip("'")
                            if item:
                                target_id = _safe_id(item)
                                if target_id != node_id:
                                    nodes.setdefault(
                                        target_id,
                                        {"name": item, "category": "other"},
                                    )
                                    edges.append((node_id, target_id))
                    elif line.startswith("- "):
                        # 多行 related 列表格式
                        item = line[2:].strip().strip('"').strip("'")
                        if item:
                            target_id = _safe_id(item)
                            if target_id != node_id:
                                nodes.setdefault(
                                    target_id,
                                    {"name": item, "category": "other"},
                                )
                                edges.append((node_id, target_id))

        # 从正文提取 [[双链]] 引用
        for m in re.finditer(r"\[\[([^\]]+)\]\]", text):
            ref_name = m.group(1).strip()
            ref_id = _safe_id(ref_name)
            if ref_id != node_id and ref_id:
                nodes.setdefault(ref_id, {"name": ref_name, "category": "other"})
                edges.append((node_id, ref_id))

    if not nodes:
        return False

    # 去重边
    edges = list(set(edges))

    # 只保留有连线的节点（去掉孤立节点）
    connected_ids = set()
    for src, dst in edges:
        connected_ids.add(src)
        connected_ids.add(dst)

    # 如果没有连线，显示所有节点
    if not connected_ids:
        connected_ids = set(nodes.keys())

    # 样式映射
    style_map = {
        "article": "fill:#4a9eff,stroke:#2b7de9,color:#fff",
        "concept": "fill:#10b981,stroke:#059669,color:#fff",
        "entity": "fill:#f59e0b,stroke:#d97706,color:#fff",
        "other": "fill:#6b7280,stroke:#4b5563,color:#fff",
    }

    # 生成 mermaid graph
    lines = [
        "---",
        "hide:",
        "  - navigation",
        "---",
        "",
        "# 知识图谱",
        "",
        "节点颜色：",
        '<span style="color:#4a9eff">**■ 文章**</span> · '
        '<span style="color:#10b981">**■ 概念**</span> · '
        '<span style="color:#f59e0b">**■ 实体**</span>',
        "",
        "```mermaid",
        "graph TD",
    ]

    # 按类型分组输出节点
    for nid, info in nodes.items():
        if nid not in connected_ids:
            continue
        name = info["name"]
        # 短标签：最多 12 个字符
        display = name if len(name) <= 12 else name[:10] + ".."
        # 转义双引号
        display = display.replace('"', "'")
        lines.append(f'    {nid}["{display}"]')

    lines.append("")

    for src, dst in edges:
        lines.append(f"    {src} --> {dst}")

    lines.append("")

    # 添加样式
    for nid, info in nodes.items():
        if nid not in connected_ids:
            continue
        cat = info["category"]
        if cat in style_map:
            lines.append(f"    style {nid} {style_map[cat]}")

    lines.append("```")
    lines.append("")
    lines.append(f"<small>{len(connected_ids)} 个节点 · {len(edges)} 条关联</small>")

    graph_path = wiki_dir / "graph.md"
    graph_path.write_text("\n".join(lines), encoding="utf-8")
    return True


def _safe_id(name: str) -> str:
    """把名称转为 mermaid 安全的节点 ID（短哈希，避免冲突）。"""
    import hashlib
    import re

    # 用 hash 生成短 ID，避免中文和特殊字符问题
    clean = re.sub(r"\s+", "", name.strip().lower())
    h = hashlib.md5(clean.encode()).hexdigest()[:8]
    # 前缀用字母开头（mermaid 要求）
    return f"n{h}"


# ---------------------------------------------------------------------------
# 入口
# ---------------------------------------------------------------------------


def main():
    cfg = load_config()

    if not cfg.vault_path.exists():
        print(f"vault 不存在: {cfg.vault_path}")
        print("请先设置 AKASHA_VAULT_PATH 并运行 akasha init")
        sys.exit(1)

    cmd = sys.argv[1] if len(sys.argv) > 1 else "serve"

    if cmd not in ("serve", "build", "deploy"):
        print("用法: akasha-site [serve|build|deploy]")
        print("  serve   本地预览 http://127.0.0.1:8000 (默认)")
        print("  build   构建静态站点到 vault/site/")
        print("  deploy  发布到 GitHub Pages")
        sys.exit(1)

    # 预处理：双链渲染（写到 _build_docs，不修改源文件）+ 生成图谱页面（写到源文件，这是新内容）
    link_map = _build_wikilink_map(cfg.docs_dir)
    graph_generated = _generate_graph_page(cfg.docs_dir, link_map)
    replaced = _resolve_wikilinks(cfg.docs_dir, link_map)
    if replaced:
        print(f"双链:       {replaced} 个 [[wikilink]] 已渲染")
    if graph_generated:
        print(f"图谱:       wiki/graph.md 已生成")

    # mkdocs 使用 _build_docs 目录（双链已替换），如果不存在则用原 docs
    build_docs_dir = cfg.docs_dir.parent / "_build_docs"
    actual_docs_dir = build_docs_dir if build_docs_dir.exists() else cfg.docs_dir

    # 生成 mkdocs.yml 到 vault 根目录
    mkdocs_config = _generate_mkdocs_config(cfg)
    mkdocs_config["docs_dir"] = str(actual_docs_dir)
    mkdocs_config["nav"] = _build_nav(actual_docs_dir)
    yml_path = cfg.vault_path / "mkdocs.yml"
    yml_path.write_text(
        yaml.dump(
            mkdocs_config, allow_unicode=True, default_flow_style=False, sort_keys=False
        ),
        encoding="utf-8",
    )

    print(f"vault:      {cfg.vault_path}")
    print(f"docs:       {cfg.docs_dir}")
    print(f"site:       {cfg.site_dir}")
    print(f"mkdocs.yml: {yml_path}")

    if cmd == "deploy":
        _deploy(cfg, yml_path)
    elif cmd == "serve":
        # serve 模式：后台定期刷新 mkdocs.yml（新页面自动出现在导航中）
        import threading
        import time

        def _refresh_config():
            while True:
                time.sleep(30)
                try:
                    new_link_map = _build_wikilink_map(cfg.docs_dir)
                    _generate_graph_page(cfg.docs_dir, new_link_map)
                    _resolve_wikilinks(cfg.docs_dir, new_link_map)
                    new_config = _generate_mkdocs_config(cfg)
                    new_config["docs_dir"] = str(actual_docs_dir)
                    new_config["nav"] = _build_nav(actual_docs_dir)
                    yml_path.write_text(
                        yaml.dump(
                            new_config,
                            allow_unicode=True,
                            default_flow_style=False,
                            sort_keys=False,
                        ),
                        encoding="utf-8",
                    )
                except Exception:
                    pass

        refresh_thread = threading.Thread(target=_refresh_config, daemon=True)
        refresh_thread.start()

        host = os.getenv("AKASHA_SITE_HOST", "127.0.0.1")
        mkdocs_cmd = [
            sys.executable,
            "-m",
            "mkdocs",
            "serve",
            "-f",
            str(yml_path),
            "-a",
            f"{host}:8800",
        ]
        print(f"url:        http://{host}:8800")
        subprocess.run(mkdocs_cmd, check=True)
    else:
        mkdocs_cmd = [sys.executable, "-m", "mkdocs", cmd, "-f", str(yml_path)]
        subprocess.run(mkdocs_cmd, check=True)


def _deploy(cfg, yml_path: Path):
    """构建站点并自动发布到 GitHub Pages。"""
    from datetime import datetime

    site_repo = cfg.site_repo
    if not site_repo:
        print("错误: 未配置 AKASHA_SITE_REPO")
        print("请设置环境变量，例如:")
        print('  export AKASHA_SITE_REPO="https://github.com/user/user.github.io.git"')
        sys.exit(1)

    site_dir = cfg.site_dir

    # 1. 构建
    print(">>> 构建站点...")
    mkdocs_cmd = [sys.executable, "-m", "mkdocs", "build", "-f", str(yml_path)]
    subprocess.run(mkdocs_cmd, check=True)

    # 2. 初始化 git（如果还没有）
    git_dir = site_dir / ".git"
    if not git_dir.exists():
        print(">>> 初始化 git...")
        subprocess.run(["git", "init"], cwd=site_dir, check=True)
        subprocess.run(
            ["git", "remote", "add", "origin", site_repo],
            cwd=site_dir,
            check=True,
        )
    else:
        # 确保 remote 地址正确
        result = subprocess.run(
            ["git", "remote", "get-url", "origin"],
            cwd=site_dir,
            capture_output=True,
            text=True,
        )
        if result.returncode != 0 or result.stdout.strip() != site_repo:
            subprocess.run(
                ["git", "remote", "set-url", "origin", site_repo],
                cwd=site_dir,
            )

    # 3. 提交并推送
    print(">>> 提交并推送...")
    subprocess.run(["git", "add", "."], cwd=site_dir, check=True)

    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    result = subprocess.run(
        ["git", "commit", "-m", f"deploy wiki {ts}"],
        cwd=site_dir,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0 and "nothing to commit" in result.stdout:
        print(">>> 没有变更，跳过推送")
        return

    subprocess.run(
        ["git", "push", "-u", "origin", "main", "--force"],
        cwd=site_dir,
        check=True,
    )
    print(f">>> 部署完成!")


if __name__ == "__main__":
    main()
