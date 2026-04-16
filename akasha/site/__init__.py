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

    # 预处理
    from .resources import generate_resources_page

    link_map = _build_wikilink_map(cfg.docs_dir)
    graph_generated = _generate_graph_page(cfg.docs_dir, link_map)
    resources_generated = generate_resources_page(cfg.docs_dir)
    replaced = _resolve_wikilinks(cfg.docs_dir, link_map)
    if replaced:
        print(f"双链:       {replaced} 个 [[wikilink]] 已渲染")
    if graph_generated:
        print("图谱:       wiki/graph.md 已生成")
    if resources_generated:
        print("资源:       wiki/resources.md 已生成")

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
        import threading
        import time

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

        # 用可替换的进程对象管理 mkdocs serve
        _lock = threading.Lock()
        _proc = [None]  # 用列表包装以便在闭包里修改

        def _start_mkdocs():
            with _lock:
                if _proc[0] and _proc[0].poll() is None:
                    _proc[0].terminate()
                    _proc[0].wait(timeout=5)
                _proc[0] = subprocess.Popen(mkdocs_cmd)

        def _refresh_loop():
            while True:
                time.sleep(30)
                try:
                    new_link_map = _build_wikilink_map(cfg.docs_dir)
                    _generate_graph_page(cfg.docs_dir, new_link_map)
                    generate_resources_page(cfg.docs_dir)
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
                    # 重启 mkdocs serve 以加载新内容
                    _start_mkdocs()
                except Exception:
                    pass

        print(f"url:        http://{host}:8800")
        _start_mkdocs()

        refresh_thread = threading.Thread(target=_refresh_loop, daemon=True)
        refresh_thread.start()

        # 主线程等待 mkdocs 进程
        try:
            while True:
                with _lock:
                    proc = _proc[0]
                if proc:
                    proc.wait()
                time.sleep(1)
        except KeyboardInterrupt:
            with _lock:
                if _proc[0] and _proc[0].poll() is None:
                    _proc[0].terminate()
    else:
        mkdocs_cmd = [sys.executable, "-m", "mkdocs", cmd, "-f", str(yml_path)]
        subprocess.run(mkdocs_cmd, check=True)


if __name__ == "__main__":
    main()
