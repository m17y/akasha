"""
Akasha MCP Server

模块化架构:
- config.py    — 配置集中管理（含 LLM 配置）
- chunker.py   — Markdown 按标题切分
- store.py     — ChromaDB 向量存储封装
- indexer.py   — 扫描→切分→增量索引
- llm.py       — LLM 客户端封装（OpenAI 兼容）
- ingester.py  — 知识摄入器（LLM Wiki 核心）

7 个 MCP tools:
- search_knowledge  — 语义搜索（支持 tag 过滤）
- list_notes        — 列出所有已索引笔记
- read_note         — 读取笔记全文
- refresh_index     — 增量/全量刷新索引
- ingest_source     — 摄入源文件 → LLM 提取知识 → 创建/更新 wiki 页面
- save_as_page      — 把好回答存为 wiki 页面
- lint_wiki         — Wiki 健康检查

搜索/索引: 无需 API Key（ChromaDB 内置本地 embedding）
知识维护 (ingest/save/lint): 需要 LLM API Key
"""

from mcp.server.fastmcp import FastMCP

from .config import load_config
from .events import (
    emit,
    Timer,
    SEARCH_QUERY,
    SEARCH_RESULT,
    INGEST_STARTED,
    INGEST_COMPLETED,
    INGEST_FAILED,
    SAVE_PAGE,
    LINT_COMPLETED,
    SECURITY_BLOCKED,
    SKILL_LOADED,
)
from .indexer import Indexer
from .store import VectorStore

# ---------------------------------------------------------------------------
# 初始化
# ---------------------------------------------------------------------------

config = load_config()

mcp = FastMCP("akasha")

_store: VectorStore | None = None
_indexer: Indexer | None = None


def get_store() -> VectorStore:
    """懒初始化 VectorStore。"""
    global _store
    if _store is None:
        _store = VectorStore(
            chroma_dir=config.chroma_dir,
            collection_name=config.collection_name,
        )
    return _store


def get_indexer() -> Indexer:
    """懒初始化 Indexer。"""
    global _indexer
    if _indexer is None:
        _indexer = Indexer(config=config, store=get_store())
    return _indexer


def ensure_indexed() -> None:
    """确保索引已构建（首次调用时增量索引）。"""
    store = get_store()
    if store.count() == 0:
        get_indexer().index_all(force=True)
    else:
        get_indexer().refresh()


# ---------------------------------------------------------------------------
# MCP Tools — 查询类（不需要 LLM）
# ---------------------------------------------------------------------------


@mcp.tool()
async def search_knowledge(
    query: str,
    top_k: int = 0,
    tags: str = "",
) -> str:
    """从个人知识库中语义搜索相关内容。

    Args:
        query: 搜索问题，用自然语言描述你想找什么
        top_k: 返回最相关的结果数量（默认5条，设为0使用默认值）
        tags: 按标签过滤，逗号分隔（如 "hive,sql"），留空不过滤
    """
    ensure_indexed()
    store = get_store()

    if store.count() == 0:
        return "知识库为空，没有可搜索的内容。"

    k = top_k if top_k > 0 else config.default_top_k
    tag_list = [t.strip() for t in tags.split(",") if t.strip()] if tags else None

    emit(SEARCH_QUERY, query=query, top_k=k, tags=tags or "(none)")
    results = store.search(query=query, top_k=k, tags=tag_list)
    emit(SEARCH_RESULT, query=query, hits=len(results))

    if not results:
        return f'没有找到与 "{query}" 相关的内容。'

    parts = [f"找到 {len(results)} 条相关内容:\n"]
    for i, hit in enumerate(results, 1):
        score_pct = f"{hit.score:.0%}"
        parts.append(f"### [{i}] {hit.heading} ({score_pct})")

        meta_parts = [f"来源: `{hit.source}`"]
        if hit.tags:
            meta_parts.append(f"标签: {hit.tags}")
        if hit.date:
            meta_parts.append(f"日期: {hit.date}")
        parts.append(" | ".join(meta_parts) + "\n")

        content = hit.content
        if len(content) > config.max_display_length:
            content = (
                content[: config.max_display_length]
                + f"\n...[截断，完整内容共 {len(hit.content)} 字符。"
                + f" 使用 read_note('{hit.source}') 查看完整内容]"
            )
        parts.append(content)
        parts.append("")

    return "\n".join(parts)


@mcp.tool()
async def list_notes() -> str:
    """列出知识库中所有已索引的笔记文件。"""
    ensure_indexed()
    store = get_store()

    if store.count() == 0:
        return "知识库为空。"

    sources = store.get_all_sources()

    parts = [f"知识库中共 {len(sources)} 个文件，{store.count()} 个 chunks:\n"]
    for info in sources:
        line = f"- `{info['source']}` ({info['chunk_count']} chunks)"
        if info.get("title"):
            line += f" — {info['title']}"
        if info.get("tags"):
            line += f" [{info['tags']}]"
        parts.append(line)

    return "\n".join(parts)


@mcp.tool()
async def read_note(file_path: str, offset: int = 0) -> str:
    """读取某篇笔记的内容。

    Args:
        file_path: 笔记文件的相对路径（相对于 docs 目录）
        offset: 从第几个字符开始读取（用于分页读取大文件，默认 0）
    """
    # L4 安全: 先校验路径合法性，再检查文件存在
    import os

    if ".." in file_path:
        return f"路径不在 vault 范围内: {file_path}"

    full_path = config.docs_dir / file_path
    resolved = full_path.resolve()
    docs_resolved = config.docs_dir.resolve()

    if (
        not str(resolved).startswith(str(docs_resolved) + os.sep)
        and resolved != docs_resolved
    ):
        return f"路径不在 vault 范围内: {file_path}"

    if not full_path.exists():
        return f"文件不存在: {file_path}"
    if not full_path.is_file():
        return f"不是文件: {file_path}"

    try:
        content = full_path.read_text(encoding="utf-8")
        total = len(content)

        if offset > 0:
            content = content[offset:]

        if len(content) > config.max_read_length:
            return (
                content[: config.max_read_length]
                + f"\n\n[截断: 完整文件共 {total} 字符，当前 offset={offset}。"
                + f" 使用 read_note('{file_path}', offset={offset + config.max_read_length}) 继续读取]"
            )
        return content
    except Exception as e:
        return f"读取失败: {e}"


@mcp.tool()
async def refresh_index(force: bool = False) -> str:
    """重新构建知识库索引。

    Args:
        force: 是否强制全量重建（默认增量更新，只处理修改过的文件）
    """
    global _store, _indexer
    if force:
        _store = None
        _indexer = None

    indexer = get_indexer()
    stats = indexer.index_all(force=force)
    return stats.summary()


# ---------------------------------------------------------------------------
# MCP Tools — 知识维护类（需要 LLM）
# ---------------------------------------------------------------------------


def _get_ingester():
    """懒初始化 Ingester（需要 LLM 配置）。"""
    from .ingester import Ingester
    from .llm import LLMClient

    llm = LLMClient(config)
    return Ingester(config=config, llm=llm)


@mcp.tool()
async def ingest_source(file_path: str) -> str:
    """摄入一个源文件到知识库。

    LLM 会读取内容，提取关键概念和实体，创建或更新 wiki 页面，
    更新 index.md 和 log.md。单次摄入可能创建多个 wiki 页面。

    需要配置 LLM API Key（环境变量 KNOWLEDGE_LLM_API_KEY）。

    Args:
        file_path: 源文件的相对路径（如 raw/analysis/autoagent-analysis.md）
    """
    if not config.llm_configured:
        return (
            "LLM 未配置，无法执行 ingest。请设置环境变量:\n"
            "  KNOWLEDGE_LLM_API_KEY=sk-xxx\n"
            "  KNOWLEDGE_LLM_BASE_URL=... (可选)\n"
            "  KNOWLEDGE_LLM_MODEL=... (可选，默认 gpt-4o)"
        )

    emit(INGEST_STARTED, source=file_path)
    try:
        ingester = _get_ingester()
        with Timer() as t:
            result = await ingester.ingest(file_path)

        # ingest 后刷新向量索引
        get_indexer().refresh()

        emit(
            INGEST_COMPLETED,
            source=file_path,
            pages_created=len(result.pages_created),
            pages_updated=len(result.pages_updated),
            duration=t.elapsed,
        )
        return result.summary()
    except FileNotFoundError as e:
        emit(INGEST_FAILED, source=file_path, error=str(e))
        return str(e)
    except Exception as e:
        emit(INGEST_FAILED, source=file_path, error=str(e))
        return f"摄入失败: {e}"


@mcp.tool()
async def save_as_page(
    title: str,
    content: str,
    category: str = "synthesis",
) -> str:
    """把一段有价值的内容保存为 wiki 页面。

    用途: 保存好的回答、分析、对比，让知识不消失在聊天记录里。
    需要配置 LLM API Key。

    Args:
        title: 页面标题
        content: 页面内容（Markdown）
        category: 分类 (concepts/entities/comparisons/synthesis)
    """
    if not config.llm_configured:
        return "LLM 未配置，无法执行 save_as_page。请设置 KNOWLEDGE_LLM_API_KEY。"

    valid_categories = {"concepts", "entities", "comparisons", "synthesis"}
    if category not in valid_categories:
        return f"无效分类: {category}，可选: {', '.join(sorted(valid_categories))}"

    try:
        ingester = _get_ingester()
        page_path = await ingester.save_as_page(title, content, category)

        # 刷新向量索引
        get_indexer().refresh()

        return f"已保存为: {page_path}"
    except Exception as e:
        return f"保存失败: {e}"


@mcp.tool()
async def lint_wiki() -> str:
    """Wiki 健康检查。

    检查 wiki 页面的规范性: 缺失 frontmatter、孤立页面、引用过少、空页面。
    不需要 LLM，纯规则检查。
    """
    from .ingester import Ingester, LintIssue

    # lint 不需要 LLM，但需要 Ingester 实例
    # 用一个 dummy 方式: 直接调用类方法
    class _DummyLLM:
        pass

    ingester = Ingester.__new__(Ingester)
    ingester.config = config
    ingester.llm = _DummyLLM()  # type: ignore

    issues = ingester.lint()

    if not issues:
        return "Wiki 健康检查通过，没有发现问题。"

    parts = [f"发现 {len(issues)} 个问题:\n"]
    for issue in issues:
        parts.append(f"- **[{issue.type}]** `{issue.page}`")
        parts.append(f"  {issue.description}")
        parts.append(f"  建议: {issue.suggestion}")
        parts.append("")

    return "\n".join(parts)


# ---------------------------------------------------------------------------
# Skill 动态注册
# ---------------------------------------------------------------------------


def _register_skill_tools() -> int:
    """扫描 skills/ 目录，动态注册 Skill tools。返回注册数量。"""
    from pathlib import Path
    from .skills import discover_skills, load_executor

    skills_dir = Path(__file__).parent / "skills"
    skills = discover_skills(skills_dir)
    registered = 0

    for skill in skills:
        try:
            executor = load_executor(skill)
        except Exception as e:
            print(f"[akasha] skill {skill.name} 加载 executor 失败: {e}")
            continue

        # 将 skill.md 中定义的每个 tool 映射到 executor 的方法
        tool_method_map = {
            "video_download": "download",
            "video_info": "info",
            "video_to_wiki": "to_wiki",
        }

        for tool_name in skill.tools:
            method_name = tool_method_map.get(
                tool_name,
                tool_name.replace(f"{skill.name}_", ""),
            )
            handler = getattr(executor, method_name, None)
            if handler is None:
                print(
                    f"[akasha] skill {skill.name}: 方法 {method_name} 不存在，跳过 {tool_name}"
                )
                continue

            # 为每个 tool 创建包装函数并注册
            _register_one_tool(mcp, tool_name, skill, handler)
            registered += 1

    return registered


def _register_one_tool(mcp_instance, tool_name: str, skill, handler):
    """注册单个 Skill tool 到 MCP。

    需要用闭包捕获 handler，否则所有 tool 会指向同一个方法。
    """
    # 根据 tool_name 构建不同的包装函数
    if tool_name == "video_download":

        @mcp_instance.tool()
        async def video_download(url: str) -> str:
            """下载视频到知识库 assets 目录（支持抖音、B站、YouTube）。

            Args:
                url: 视频链接
            """
            docs_dir = config.docs_dir if config.docs_dir.exists() else None
            return await handler(url, docs_dir=docs_dir)

    elif tool_name == "video_info":

        @mcp_instance.tool()
        async def video_info(url: str) -> str:
            """获取视频信息（标题、作者、时长等），不下载。

            Args:
                url: 视频链接
            """
            info = await handler(url)
            return info.to_summary()

    elif tool_name == "video_to_wiki":

        @mcp_instance.tool()
        async def video_to_wiki(url: str) -> str:
            """下载视频并生成带嵌入播放器的 wiki 页面。

            Args:
                url: 视频链接
            """
            docs_dir = config.docs_dir if config.docs_dir.exists() else None
            page_path = await handler(url, docs_dir=docs_dir)

            # 刷新索引
            if docs_dir:
                get_indexer().refresh()

            return f"已生成 wiki 页面: {page_path}"


# ---------------------------------------------------------------------------
# 入口
# ---------------------------------------------------------------------------


def _init_vault() -> None:
    """首次启动时自动创建 vault 目录结构。"""
    vault = config.vault_path
    docs = config.docs_dir

    if not vault.exists():
        print(f"[akasha] 首次启动，创建 vault: {vault}")

    vault.mkdir(parents=True, exist_ok=True)
    docs.mkdir(parents=True, exist_ok=True)
    config.site_dir.mkdir(parents=True, exist_ok=True)

    # 创建 docs/ 下的子目录
    for subdir in [
        "raw/analysis",
        "raw/notes",
        "raw/articles",
        "wiki/concepts",
        "wiki/entities",
        "wiki/comparisons",
        "wiki/synthesis",
    ]:
        (docs / subdir).mkdir(parents=True, exist_ok=True)

    # 创建 schema.md（如果不存在）
    if not config.schema_path.exists():
        config.schema_path.write_text(
            "# Knowledge Wiki Schema\n\n"
            "> 本文件定义 wiki 规则。详见 DESIGN.md。\n\n"
            "将你的自定义 schema 规则写在这里。\n",
            encoding="utf-8",
        )

    # 创建 index.md（如果不存在）
    if not config.index_path.exists():
        config.index_path.write_text(
            "# 知识库目录\n\n"
            "> 自动维护，每次 ingest 或 save_as_page 后更新。\n\n---\n\n"
            "## 概念 (concepts/)\n\n*暂无条目 — 执行 ingest 后自动生成。*\n\n"
            "## 实体 (entities/)\n\n*暂无条目 — 执行 ingest 后自动生成。*\n\n"
            "## 对比 (comparisons/)\n\n*暂无条目 — 执行 ingest 后自动生成。*\n\n"
            "## 综合 (synthesis/)\n\n*暂无条目 — 执行 save_as_page 后自动生成。*\n",
            encoding="utf-8",
        )

    # 创建 log.md（如果不存在）
    if not config.log_path.exists():
        config.log_path.write_text(
            "# 知识库日志\n\n> Append-only. 每次 ingest / save_as_page 自动追加。\n\n---\n",
            encoding="utf-8",
        )


def _print_status():
    """打印当前配置状态。"""
    print(f"vault:      {config.vault_path}")
    print(f"docs:       {config.docs_dir}")
    print(f"chroma:     {config.chroma_dir}")
    print(f"embedding:  ChromaDB 内置 (all-MiniLM-L6-v2, 本地运行)")
    if config.llm_configured:
        print(f"llm:        {config.llm_model} @ {config.llm_base_url}")
    else:
        print(f"llm:        未配置 (ingest/save 不可用，搜索正常)")


def _print_help():
    """打印帮助信息。"""
    print("Akasha — 个人知识库 MCP Server")
    print()
    print("用法:")
    print("  akasha              启动 MCP Server (stdio 模式，供 AI 客户端调用)")
    print("  akasha init         初始化 vault 目录结构")
    print("  akasha status       查看配置和索引状态")
    print("  akasha help         显示此帮助")
    print()
    print("  akasha-site serve   启动知识库网站预览 (http://127.0.0.1:8800)")
    print("  akasha-site build   构建静态站点到 vault/site/")
    print("  akasha-site deploy  发布到 GitHub Pages")
    print()
    print("环境变量:")
    print(f"  AKASHA_VAULT_PATH   vault 根目录 (当前: {config.vault_path})")
    print(f"  AKASHA_CHROMA_DIR   ChromaDB 目录 (当前: {config.chroma_dir})")
    print(
        f"  AKASHA_LLM_API_KEY  LLM API Key (当前: {'已配置' if config.llm_configured else '未配置'})"
    )
    print(f"  AKASHA_LLM_BASE_URL LLM 端点 (当前: {config.llm_base_url})")
    print(f"  AKASHA_LLM_MODEL    LLM 模型 (当前: {config.llm_model})")
    print()
    print("MCP Tools:")
    print("  search_knowledge    语义搜索笔记 (支持 tag 过滤)")
    print("  list_notes          列出所有已索引文件")
    print("  read_note           读取笔记全文")
    print("  refresh_index       刷新索引 (增量/全量)")
    print("  ingest_source       摄入源文件 → LLM 提取概念 → 生成 wiki 页面")
    print("  save_as_page        把好回答存为 wiki 页面")
    print("  lint_wiki           Wiki 健康检查")
    print()
    print("Skill Tools (可插拔):")
    print("  video_download      下载视频 (抖音/B站/YouTube)")
    print("  video_info          获取视频信息 (不下载)")
    print("  video_to_wiki       解析视频 → 生成 wiki 页面")


def main():
    import sys

    cmd = sys.argv[1] if len(sys.argv) > 1 else "serve"

    if cmd in ("help", "--help", "-h"):
        _print_help()
        return

    if cmd == "init":
        _init_vault()
        _print_status()
        print()
        print("vault 初始化完成。")
        return

    if cmd == "status":
        _print_status()
        _init_vault()
        ensure_indexed()
        store = get_store()
        sources = store.get_all_sources()
        print(f"已索引:     {len(sources)} 个文件, {store.count()} 个 chunks")
        return

    # 默认: 启动 MCP Server
    if cmd not in ("serve", "start"):
        print(f"未知命令: {cmd}")
        print("运行 akasha help 查看帮助")
        sys.exit(1)

    _init_vault()
    ensure_indexed()
    skill_count = _register_skill_tools()
    _print_status()
    store = get_store()
    print(
        f"已索引:     {len(store.get_all_sources())} 个文件, {store.count()} 个 chunks"
    )
    if skill_count:
        print(f"skills:     {skill_count} 个 tool 已注册")
    print(f"启动 MCP Server (stdio)...")
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
