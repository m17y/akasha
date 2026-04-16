"""
MCP Server — 薄壳接入层。

两种模式:
- ask: 用户说一句话 → Agent 自己决定做什么（推荐）
- 细粒度 tools: search / read / list / ingest 等（向后兼容）
"""

from mcp.server.fastmcp import FastMCP

from ..vault import Vault

# ---------------------------------------------------------------------------
# 初始化
# ---------------------------------------------------------------------------

vault = Vault()
mcp = FastMCP("akasha")


# ---------------------------------------------------------------------------
# Agent 模式（推荐）
# ---------------------------------------------------------------------------


@mcp.tool()
async def ask(message: str) -> str:
    """用自然语言和知识库交互。

    Akasha Agent 会理解你的意图，自动搜索、摄入、下载视频、剪藏网页等。
    不需要手动选择工具，直接说你想做什么即可。

    Args:
        message: 你想做什么（自然语言）
    """
    return await vault.ask(message)


# ---------------------------------------------------------------------------
# 细粒度 Tools（向后兼容）
# ---------------------------------------------------------------------------


@mcp.tool()
async def search_knowledge(query: str, top_k: int = 0, tags: str = "") -> str:
    """从个人知识库中语义搜索相关内容。

    Args:
        query: 搜索问题，用自然语言描述你想找什么
        top_k: 返回最相关的结果数量（默认5条，设为0使用默认值）
        tags: 按标签过滤，逗号分隔（如 "hive,sql"），留空不过滤
    """
    return vault.search_formatted(query, top_k=top_k, tags=tags)


@mcp.tool()
async def list_notes() -> str:
    """列出知识库中所有已索引的笔记文件。"""
    return vault.list_notes_formatted()


@mcp.tool()
async def read_note(file_path: str, offset: int = 0) -> str:
    """读取某篇笔记的内容。

    Args:
        file_path: 笔记文件的相对路径（相对于 docs 目录）
        offset: 从第几个字符开始读取（用于分页读取大文件，默认 0）
    """
    return vault.read_formatted(file_path, offset=offset)


@mcp.tool()
async def refresh_index(force: bool = False) -> str:
    """重新构建知识库索引。

    Args:
        force: 是否强制全量重建（默认增量更新，只处理修改过的文件）
    """
    stats = vault.refresh_index(force=force)
    return stats.summary()


@mcp.tool()
async def ingest_source(file_path: str) -> str:
    """摄入一个源文件到知识库。

    LLM 会读取内容，提取关键概念和实体，创建或更新 wiki 页面。

    Args:
        file_path: 源文件的相对路径（如 raw/analysis/xxx.md）
    """
    return await vault.ingest(file_path)


@mcp.tool()
async def save_as_page(title: str, content: str, category: str = "synthesis") -> str:
    """把一段有价值的内容保存为 wiki 页面。

    Args:
        title: 页面标题
        content: 页面内容（Markdown）
        category: 分类 (concepts/entities/comparisons/synthesis)
    """
    return await vault.save_page(title, content, category)


@mcp.tool()
async def lint_wiki() -> str:
    """Wiki 健康检查。检查缺失 frontmatter、孤立页面、引用不足、空页面。"""
    return vault.lint()


# ---------------------------------------------------------------------------
# Skill Tools — 动态注册
# ---------------------------------------------------------------------------


def _register_skill_tools() -> int:
    """把 Vault 加载的 skills 注册为 MCP tools。"""
    count = vault.load_skills()

    for action in vault.skill_registry.get_all_actions():
        _register_one_skill_tool(action)

    return count


def _register_one_skill_tool(action):
    """注册单个 skill action 为 MCP tool。"""
    tool_name = action.tool_name
    handler = action.handler
    docs_dir = vault.config.docs_dir

    if tool_name == "video_download":

        @mcp.tool()
        async def video_download(url: str) -> str:
            """下载视频到知识库（支持抖音、B站、YouTube）。

            Args:
                url: 视频链接
            """
            return await handler(url, docs_dir=docs_dir if docs_dir.exists() else None)

    elif tool_name == "video_info":

        @mcp.tool()
        async def video_info(url: str) -> str:
            """获取视频信息（不下载）。

            Args:
                url: 视频链接
            """
            info = await handler(url)
            return info.to_summary()

    elif tool_name == "video_to_wiki":

        @mcp.tool()
        async def video_to_wiki(url: str) -> str:
            """下载视频并生成 wiki 页面。

            Args:
                url: 视频链接
            """
            page_path = await handler(
                url, docs_dir=docs_dir if docs_dir.exists() else None
            )
            vault.index.refresh()
            return f"已生成 wiki 页面: {page_path}"

    elif tool_name == "web_clip_save":

        @mcp.tool()
        async def web_clip_save(url: str, category: str = "articles") -> str:
            """剪藏网页 — 提取正文保存为 wiki 页面。

            Args:
                url: 网页链接
                category: 保存分类
            """
            page_path = await handler(
                url,
                docs_dir=docs_dir if docs_dir.exists() else None,
                category=category,
            )
            vault.index.refresh()
            return f"已保存: {page_path}"

    elif tool_name == "web_clip_read":

        @mcp.tool()
        async def web_clip_read(url: str) -> str:
            """提取网页正文（不保存），返回 Markdown。

            Args:
                url: 网页链接
            """
            return await handler(url)

    elif tool_name == "media_transcribe":

        @mcp.tool()
        async def media_transcribe(source: str) -> str:
            """提取音视频中的语音，转为文字稿。

            Args:
                source: 本地文件路径或 URL
            """
            return await handler(source)

    elif tool_name == "media_to_wiki":

        @mcp.tool()
        async def media_to_wiki(source: str, title: str = "") -> str:
            """提取音视频语音 → 生成 wiki 页面。

            Args:
                source: 本地文件路径或 URL
                title: 页面标题（不填则自动生成）
            """
            page_path = await handler(
                source,
                title=title,
                docs_dir=docs_dir if docs_dir.exists() else None,
            )
            vault.index.refresh()
            return f"已生成: {page_path}"


# ---------------------------------------------------------------------------
# 入口
# ---------------------------------------------------------------------------


def main():
    import sys

    cmd = sys.argv[1] if len(sys.argv) > 1 else "help"

    if cmd in ("help", "--help", "-h"):
        _print_help()
        return

    if cmd == "init":
        vault.init()
        print(vault.status_formatted())
        print("\nvault 初始化完成。")
        return

    if cmd == "status":
        vault.init()
        vault.ensure_indexed()
        print(vault.status_formatted())
        return

    if cmd == "site":
        from ..site import main as site_main

        sys.argv = ["akasha-site"] + sys.argv[2:]
        site_main()
        return

    if cmd == "refresh":
        import asyncio

        vault.init()
        vault.ensure_indexed()
        sub = sys.argv[2] if len(sys.argv) > 2 else ""
        if sub == "concepts":
            result = asyncio.run(vault.refresh_concepts())
            print(result)
        elif sub == "index":
            stats = vault.refresh_index(force=True)
            print(stats.summary())
        else:
            print("用法:")
            print("  akasha refresh concepts   重新生成所有概念页面")
            print("  akasha refresh index      强制刷新索引")
        return

    if cmd == "export":
        _export_vault(vault)
        return

    if cmd == "import":
        archive = sys.argv[2] if len(sys.argv) > 2 else None
        if not archive:
            print("用法: akasha import <archive.tar.gz>")
            sys.exit(1)
        _import_vault(vault, archive)
        return

    if cmd == "mcp":
        # MCP Server（stdio 模式，独占终端）
        vault.init()
        vault.ensure_indexed()
        skill_count = _register_skill_tools()
        print(vault.status_formatted())
        if skill_count:
            print(f"skills:     {skill_count} 个 tool 已注册")
        print("启动 MCP Server (stdio)...")
        mcp.run(transport="stdio")
        return

    if cmd == "start":
        _start_agent()
        return

    print(f"未知命令: {cmd}")
    print("运行 akasha help 查看帮助")
    sys.exit(1)


def _start_agent():
    """启动 Agent — 自动检测已配置的通道并启用。"""
    import os
    import sys
    import threading

    vault.init()
    vault.ensure_indexed()
    vault.load_skills()
    print(vault.status_formatted())
    print()

    # LLM 连通性检查
    if vault.config.llm_configured:
        print("--- LLM 连通性检查 ---")
        try:
            import asyncio
            from ..llm import create_llm_client

            llm = create_llm_client(vault.config)

            async def _check():
                return await llm.chat(
                    system="回复 OK 即可",
                    user="ping",
                    max_tokens=10,
                )

            result = asyncio.run(_check())
            print(f"  LLM 响应:   {result.strip()[:50]}")
            print("  状态:       连通 ✓")
        except Exception as e:
            print("  状态:       失败 ✗")
            print(f"  错误:       {type(e).__name__}: {e}")
        print()

    channels_started = []

    # 飞书通道：检测到 AKASHA_FEISHU_APP_ID 自动启用
    feishu_app_id = os.getenv("AKASHA_FEISHU_APP_ID", "")
    if feishu_app_id:
        from .feishu import main as feishu_main

        thread = threading.Thread(target=feishu_main, daemon=True)
        thread.start()
        channels_started.append("飞书")

    # Wiki 网站：检测到 AKASHA_SITE_SERVE=true 自动启用
    if os.getenv("AKASHA_SITE_SERVE", "").lower() in ("true", "1", "yes"):

        def _start_site():
            import subprocess

            try:
                subprocess.run(
                    [sys.executable, "-m", "akasha.site", "serve"],
                    check=False,
                )
            except Exception as e:
                print(f"Wiki 站点启动失败: {e}")

        site_thread = threading.Thread(target=_start_site, daemon=True)
        site_thread.start()
        channels_started.append("Wiki (8800)")

    if channels_started:
        print(f"通道:       {', '.join(channels_started)}")
        print()

        # 检测是否有交互式终端
        if sys.stdin.isatty():
            # 有终端，进入交互模式
            from .cli import _repl

            print("Agent 已启动，进入交互模式（Ctrl+C 退出）")
            print()
            try:
                _repl(vault)
            except KeyboardInterrupt:
                print("\n再见。")
        else:
            # 无终端（Docker / 后台运行），保持进程存活
            print("Agent 已启动（后台模式，Ctrl+C 退出）")
            print()
            try:
                threading.Event().wait()
            except KeyboardInterrupt:
                print("\n再见。")
    else:
        # 没有配置任何通道，直接进入 TUI
        from .cli import _repl

        print("未检测到通道配置，进入交互模式")
        print("提示: 设置 AKASHA_FEISHU_APP_ID 可启用飞书通道")
        print()
        _repl(vault)


def _export_vault(vault):
    """一键打包知识库为 tar.gz。"""
    import tarfile
    from datetime import datetime

    vault.init()
    docs_dir = vault.config.docs_dir
    if not docs_dir.exists():
        print(f"docs 目录不存在: {docs_dir}")
        return

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    archive_name = f"akasha-export-{ts}.tar.gz"
    archive_path = vault.config.vault_path / archive_name

    print(">>> 打包知识库...")
    with tarfile.open(archive_path, "w:gz") as tar:
        # 打包 docs/ (wiki、raw 等所有内容)
        tar.add(docs_dir, arcname="docs")
        # 打包 mkdocs.yml (如果存在)
        yml = vault.config.vault_path / "mkdocs.yml"
        if yml.exists():
            tar.add(yml, arcname="mkdocs.yml")

    size_mb = archive_path.stat().st_size / 1024 / 1024
    print(f">>> 打包完成: {archive_path}")
    print(f"    大小: {size_mb:.1f} MB")
    print(f"    迁移: 复制到新机器后执行 akasha import {archive_name}")


def _import_vault(vault, archive: str):
    """从 tar.gz 导入知识库。"""
    import tarfile
    from pathlib import Path

    archive_path = Path(archive)
    if not archive_path.exists():
        # 也在 vault 目录下找
        archive_path = vault.config.vault_path / archive
    if not archive_path.exists():
        print(f"文件不存在: {archive}")
        return

    vault.init()

    print(f">>> 导入知识库: {archive_path}")
    with tarfile.open(archive_path, "r:gz") as tar:
        tar.extractall(path=vault.config.vault_path, filter="data")

    print(">>> 导入完成，刷新索引...")
    vault.ensure_indexed()
    vault.index.refresh()
    print(vault.status_formatted())


def _print_help():
    print("Akasha — 个人 AI 知识库引擎")
    print()
    print("用法:")
    print("  akasha start           启动 Agent（自动检测并启用已配置的通道）")
    print("  akasha init            初始化 vault 目录结构")
    print("  akasha status          查看配置和索引状态")
    print("  akasha mcp             启动 MCP Server (stdio)")
    print("  akasha site serve      知识库网站预览")
    print("  akasha site build      构建静态站点")
    print("  akasha site deploy     发布到 GitHub Pages")
    print("  akasha refresh concepts 重新生成所有概念页面")
    print("  akasha refresh index   强制刷新索引")
    print("  akasha export          一键打包知识库为 tar.gz")
    print("  akasha import <file>   从 tar.gz 导入知识库")
    print()
    print("通道配置（通过环境变量）:")
    print("  AKASHA_FEISHU_APP_ID + AKASHA_FEISHU_APP_SECRET  → 启用飞书通道")
    print()
    print("示例:")
    print("  akasha start           # 有飞书配置则自动连飞书，同时进入交互模式")
    print("  akasha mcp             # 作为 MCP Server 给 Cursor/Claude 等调用")
