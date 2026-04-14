"""
Vault — 知识库的唯一入口。

所有操作通过 Vault 类进行，不直接依赖任何协议（MCP / HTTP / CLI）。
接入层（serve/mcp.py、serve/cli.py）调用 Vault 的方法即可。

用法:
    from akasha import Vault

    vault = Vault()                         # 使用默认配置
    vault = Vault("~/my-knowledge-base")    # 指定路径

    # 基础操作（不需要 LLM）
    vault.search("Agent Loop")
    vault.read("raw/notes/xxx.md")
    vault.list_notes()
    vault.refresh_index()

    # 知识编译（需要 LLM）
    await vault.ingest("raw/notes/xxx.md")
    await vault.save_page("标题", "内容")
    vault.lint()
"""

from __future__ import annotations

from pathlib import Path

from .config import Config, load_config
from .storage.files import FileStore, ReadResult
from .storage.index import VectorIndex, SearchResult, IndexStats
from .skills import SkillRegistry


class Vault:
    """个人知识库。

    统一入口，封装存储层 + 知识编译器 + skills。
    """

    def __init__(self, vault_path: str | Path | None = None):
        """初始化知识库。

        Args:
            vault_path: 知识库根目录。None 则使用环境变量或默认值 ~/akasha。
        """
        if vault_path is not None:
            import os

            os.environ["AKASHA_VAULT_PATH"] = str(Path(vault_path).expanduser())

        self.config = load_config()
        self.files = FileStore(self.config)
        self.index = VectorIndex(self.config)
        self.skill_registry = SkillRegistry()

        self._indexed = False
        self._compiler = None  # 懒初始化（需要 LLM）
        self._skills_loaded = False

    # ── 初始化 ──

    def init(self) -> None:
        """初始化 vault 目录结构。"""
        self.files.init_vault()

    def ensure_indexed(self) -> None:
        """确保索引已构建。首次调用时自动增量索引。"""
        if self._indexed:
            return
        if self.index.count() == 0:
            self.index.build(force=True)
        else:
            self.index.refresh()
        self._indexed = True

    # ── 搜索 ──

    def search(
        self,
        query: str,
        top_k: int = 0,
        tags: str = "",
    ) -> list[SearchResult]:
        """语义搜索笔记。

        Args:
            query: 搜索问题
            top_k: 返回结果数（0 = 使用默认值）
            tags: 按标签过滤，逗号分隔

        Returns:
            SearchResult 列表
        """
        self.ensure_indexed()

        k = top_k if top_k > 0 else self.config.default_top_k
        tag_list = [t.strip() for t in tags.split(",") if t.strip()] if tags else None
        return self.index.search(query=query, top_k=k, tags=tag_list)

    def search_formatted(
        self,
        query: str,
        top_k: int = 0,
        tags: str = "",
    ) -> str:
        """语义搜索，返回格式化的文本结果（供接入层使用）。"""
        self.ensure_indexed()

        if self.index.count() == 0:
            return "知识库为空，没有可搜索的内容。"

        results = self.search(query, top_k, tags)
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
            if len(content) > self.config.max_display_length:
                content = (
                    content[: self.config.max_display_length]
                    + f"\n...[截断，完整内容共 {len(hit.content)} 字符。"
                    + f" 使用 read('{hit.source}') 查看完整内容]"
                )
            parts.append(content)
            parts.append("")

        return "\n".join(parts)

    # ── 读取 ──

    def read(self, file_path: str, offset: int = 0) -> ReadResult:
        """读取笔记内容（支持分页）。

        Args:
            file_path: 相对于 docs 目录的路径
            offset: 从第几个字符开始读取
        """
        return self.files.read(file_path, offset)

    def read_formatted(self, file_path: str, offset: int = 0) -> str:
        """读取笔记，返回格式化文本（供接入层使用）。"""
        try:
            result = self.read(file_path, offset)
        except (ValueError, FileNotFoundError) as e:
            return str(e)

        if result.truncated:
            return (
                result.content
                + f"\n\n[截断: 完整文件共 {result.total_length} 字符，"
                + f"当前 offset={offset}。"
                + f" 使用 read('{file_path}', offset={result.next_offset}) 继续读取]"
            )
        return result.content

    # ── 列出 ──

    def list_notes(self) -> list[dict]:
        """列出所有已索引文件的信息。"""
        self.ensure_indexed()
        return self.index.get_all_sources()

    def list_notes_formatted(self) -> str:
        """列出所有笔记，返回格式化文本。"""
        self.ensure_indexed()

        if self.index.count() == 0:
            return "知识库为空。"

        sources = self.list_notes()
        parts = [f"知识库中共 {len(sources)} 个文件，{self.index.count()} 个 chunks:\n"]
        for info in sources:
            line = f"- `{info['source']}` ({info['chunk_count']} chunks)"
            if info.get("title"):
                line += f" — {info['title']}"
            if info.get("tags"):
                line += f" [{info['tags']}]"
            parts.append(line)

        return "\n".join(parts)

    # ── 索引 ──

    def refresh_index(self, force: bool = False) -> IndexStats:
        """刷新索引。

        Args:
            force: 是否强制全量重建
        """
        if force:
            # 重置内部状态
            self.index = VectorIndex(self.config)
        stats = self.index.build(force=force)
        self._indexed = True
        return stats

    # ── Skills（可插拔扩展）──

    def load_skills(self) -> int:
        """加载所有 skills，返回注册的 action 数量。"""
        if self._skills_loaded:
            return len(self.skill_registry.actions)
        count = self.skill_registry.discover_and_load()
        self._skills_loaded = True
        return count

    async def execute_skill(self, tool_name: str, **kwargs) -> str:
        """执行一个 skill action。

        Args:
            tool_name: tool 名称（如 video_download、web_clip_save）
            **kwargs: 传递给 handler 的参数

        Returns:
            执行结果文本
        """
        if not self._skills_loaded:
            self.load_skills()

        action = self.skill_registry.get_action(tool_name)
        if action is None:
            available = ", ".join(self.skill_registry.actions.keys())
            return f"未知的 skill tool: {tool_name}。可用: {available or '(无)'}"

        # 注入 docs_dir 给需要它的 handler
        if "docs_dir" not in kwargs and self.config.docs_dir.exists():
            kwargs["docs_dir"] = self.config.docs_dir

        result = await action.handler(**kwargs)

        # 某些操作后需要刷新索引（生成了 wiki 页面的）
        if "wiki" in tool_name or "save" in tool_name:
            self.index.refresh()

        if isinstance(result, str):
            return result
        return str(result)

    def get_skill_prompts(self) -> dict[str, str]:
        """获取所有 skill 的 prompt（skill.md 内容），供 Agent 使用。"""
        if not self._skills_loaded:
            self.load_skills()
        return self.skill_registry.get_skill_prompts()

    # ── 知识编译（需要 LLM）──

    def _get_compiler(self):
        """懒初始化 Compiler。"""
        if self._compiler is None:
            from .compiler import Compiler
            from .llm import create_llm_client

            llm = create_llm_client(self.config)
            self._compiler = Compiler(self.config, self.files, llm)
        return self._compiler

    async def ingest(self, source_path: str) -> str:
        """摄入源文件 → LLM 提取概念 → 创建/更新 wiki 页面。

        Args:
            source_path: 相对于 docs 的路径（如 raw/notes/xxx.md）

        Returns:
            摄入结果摘要
        """
        if not self.config.llm_configured:
            return (
                "LLM 未配置，无法执行 ingest。请设置环境变量:\n"
                "  AKASHA_LLM_API_KEY=sk-xxx"
            )

        compiler = self._get_compiler()
        result = await compiler.ingest(source_path)

        # 摄入后刷新向量索引
        self.index.refresh()

        return result.summary()

    async def save_page(
        self,
        title: str,
        content: str,
        category: str = "synthesis",
    ) -> str:
        """将内容存为 wiki 页面。

        Args:
            title: 页面标题
            content: 页面内容（Markdown）
            category: 分类 (concepts/entities/comparisons/synthesis)

        Returns:
            创建的页面路径
        """
        if not self.config.llm_configured:
            return "LLM 未配置，无法执行 save_page。请设置 AKASHA_LLM_API_KEY。"

        valid_categories = {"concepts", "entities", "comparisons", "synthesis"}
        if category not in valid_categories:
            return f"无效分类: {category}，可选: {', '.join(sorted(valid_categories))}"

        compiler = self._get_compiler()
        page_path = await compiler.save_as_page(title, content, category)

        self.index.refresh()

        return f"已保存为: {page_path}"

    def lint(self) -> str:
        """Wiki 健康检查。

        Returns:
            检查结果文本
        """
        from .compiler import Compiler

        # lint 不需要 LLM，创建一个不带 LLM 的 Compiler
        compiler = Compiler.__new__(Compiler)
        compiler.config = self.config
        compiler.files = self.files
        compiler.llm = None  # type: ignore

        issues = compiler.lint()

        if not issues:
            return "Wiki 健康检查通过，没有发现问题。"

        parts = [f"发现 {len(issues)} 个问题:\n"]
        for issue in issues:
            parts.append(f"- **[{issue.type}]** `{issue.page}`")
            parts.append(f"  {issue.description}")
            parts.append(f"  建议: {issue.suggestion}")
            parts.append("")

        return "\n".join(parts)

    # ── Agent ──

    def create_agent(self, on_step=None):
        """创建一个 Agent 实例。

        Args:
            on_step: 每步执行时的回调 (str) -> None，用于实时输出进度。

        Returns:
            AgentLoop 实例
        """
        from .agent.loop import AgentLoop

        if not self._skills_loaded:
            self.load_skills()

        return AgentLoop(self, on_step=on_step)

    async def ask(self, message: str, on_step=None) -> str:
        """用自然语言和知识库交互（通过 Agent）。

        这是最高层的接口。用户说一句话，Agent 自己决定做什么。

        Args:
            message: 用户输入

        Returns:
            Agent 的回复
        """
        agent = self.create_agent(on_step=on_step)
        return await agent.run(message)

    # ── 状态 ──

    def status(self) -> dict:
        """返回知识库状态信息。"""
        self.ensure_indexed()
        sources = self.index.get_all_sources()
        skill_count = len(self.skill_registry.actions) if self._skills_loaded else 0
        return {
            "vault_path": str(self.config.vault_path),
            "docs_dir": str(self.config.docs_dir),
            "chroma_dir": str(self.config.chroma_dir),
            "llm_configured": self.config.llm_configured,
            "llm_provider": self.config.llm_provider
            if self.config.llm_configured
            else None,
            "llm_model": self.config.llm_model_resolved
            if self.config.llm_configured
            else None,
            "llm_base_url": self.config.llm_base_url_resolved
            if self.config.llm_configured
            else None,
            "files_count": len(sources),
            "chunks_count": self.index.count(),
            "skills_count": skill_count,
        }

    def status_formatted(self) -> str:
        """返回格式化的状态文本。"""
        s = self.status()
        lines = [
            f"vault:      {s['vault_path']}",
            f"docs:       {s['docs_dir']}",
            f"chroma:     {s['chroma_dir']}",
            f"embedding:  ChromaDB 内置 (all-MiniLM-L6-v2, 本地运行)",
        ]
        if s["llm_configured"]:
            lines.append(
                f"llm:        [{s['llm_provider']}] {s['llm_model']} @ {s['llm_base_url']}"
            )
        else:
            lines.append("llm:        未配置 (ingest/save 不可用，搜索正常)")
        lines.append(
            f"已索引:     {s['files_count']} 个文件, {s['chunks_count']} 个 chunks"
        )
        if s["skills_count"]:
            lines.append(f"skills:     {s['skills_count']} 个 tool 已注册")
        return "\n".join(lines)
