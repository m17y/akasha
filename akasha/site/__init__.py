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

from ..config import load_config
from .deploy import _deploy
from .graph import _generate_graph_page
from .mkdocs_config import _build_nav, _generate_mkdocs_config
from .wikilinks import _build_wikilink_map, _resolve_wikilinks


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


if __name__ == "__main__":
    main()
