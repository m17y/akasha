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

        # 长期记忆（放在 vault_path/.memory/，不在 docs 里）
        from .memory import Memory

        self.memory = Memory(self.config.vault_path)

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

        # 注入 docs_dir 给需要它的 handler（仅当方法签名包含该参数时）
        import inspect

        if "docs_dir" not in kwargs and self.config.docs_dir.exists():
            sig = inspect.signature(action.handler)
            if "docs_dir" in sig.parameters:
                kwargs["docs_dir"] = self.config.docs_dir

        # 记录执行前的 wiki 文件 mtime（用于检测新增和修改）
        wiki_before: dict[str, float] = {}
        if self.config.docs_dir.exists() and (self.config.docs_dir / "wiki").exists():
            for p in (self.config.docs_dir / "wiki").rglob("*.md"):
                rel = str(p.relative_to(self.config.docs_dir))
                wiki_before[rel] = p.stat().st_mtime

        result = await action.handler(**kwargs)

        # 检测新增或修改的 wiki 页面
        changed_pages = set()
        if self.config.docs_dir.exists() and (self.config.docs_dir / "wiki").exists():
            for p in (self.config.docs_dir / "wiki").rglob("*.md"):
                rel = str(p.relative_to(self.config.docs_dir))
                old_mtime = wiki_before.get(rel)
                if old_mtime is None or p.stat().st_mtime > old_mtime:
                    changed_pages.add(rel)

        # post_save hooks（新增或修改都触发）
        if changed_pages:
            await self._on_pages_created(changed_pages, tool_name)

        if isinstance(result, str):
            return result
        return str(result)

    async def _on_pages_created(self, new_pages: set[str], tool_name: str) -> None:
        """新页面创建后的统一 hook。"""
        from datetime import date

        docs_dir = self.config.docs_dir
        today = date.today().isoformat()

        # Hook 1: 追加 log.md
        log_entries = [f"\n## {today}"]
        for page in sorted(new_pages):
            log_entries.append(f"- **{tool_name}** → {page}")
        self.files.append_file("log.md", "\n".join(log_entries) + "\n")

        # Hook 2: 从新文章中提取 concepts（扫描 [[双链]]）
        import re

        new_concepts: list[
            tuple[str, str, str]
        ] = []  # (ref_name, safe_name, source_page)

        for page in new_pages:
            if not page.startswith("wiki/articles/"):
                continue
            full_path = docs_dir / page
            if not full_path.exists():
                continue
            text = full_path.read_text(encoding="utf-8")
            source_name = page.split("/")[-1].replace(".md", "")

            for m in re.finditer(r"\[\[([^\]]+)\]\]", text):
                ref_name = m.group(1).strip()
                if not ref_name or _is_junk_concept(ref_name):
                    continue
                safe_name = re.sub(r"[^\w\-]", "-", ref_name.lower())[:60].strip("-")
                if not safe_name:
                    continue

                # 检查是否已存在
                existing_path = None
                for category in ("concepts", "entities"):
                    p = docs_dir / f"wiki/{category}/{safe_name}.md"
                    if p.exists():
                        existing_path = p
                        break

                if existing_path:
                    # 已存在 → 追加引用来源（如果还没有）
                    existing_text = existing_path.read_text(encoding="utf-8")
                    link = f"[[{source_name}]]"
                    if link not in existing_text:
                        existing_text = existing_text.rstrip() + f"\n- {link}\n"
                        existing_path.write_text(existing_text, encoding="utf-8")
                else:
                    new_concepts.append((ref_name, safe_name, page))

        # 批量让 LLM 生成新概念简介
        if new_concepts:
            await self._create_concept_pages(docs_dir, new_concepts, today)

        # Hook 3: 刷新索引
        self.index.refresh()

    async def _create_concept_pages(
        self, docs_dir, concepts: list[tuple[str, str, str]], today: str
    ) -> None:
        """批量创建概念页面，用 LLM 生成简介。"""
        from akasha import _get_llm_client

        llm = _get_llm_client()

        # 去重
        seen = set()
        unique = []
        for ref_name, safe_name, source in concepts:
            if safe_name not in seen:
                seen.add(safe_name)
                unique.append((ref_name, safe_name, source))

        # 从知识库文章中收集每个概念的上下文片段
        import re as _re2

        concept_contexts: dict[str, list[str]] = {}
        articles_dir = docs_dir / "wiki" / "articles"
        if articles_dir.exists():
            for md in articles_dir.rglob("*.md"):
                text = md.read_text(encoding="utf-8")
                lines = text.split("\n")
                for ref_name, _, _ in unique:
                    pattern = f"[[{ref_name}]]"
                    for i, line in enumerate(lines):
                        if pattern in line:
                            # 取前后各 2 行作为上下文
                            start = max(0, i - 2)
                            end = min(len(lines), i + 3)
                            snippet = "\n".join(lines[start:end]).strip()
                            concept_contexts.setdefault(ref_name, []).append(
                                f"（来自 {md.stem}）{snippet}"
                            )
                            break  # 每篇文章只取一段

        # 逐个生成概念页面（每个独立调 LLM，内容更丰富）
        created_count = 0
        for ref_name, safe_name, source in unique:
            # 跳过已存在的
            exists = False
            for dir_name in ("concepts", "entities"):
                if (docs_dir / f"wiki/{dir_name}/{safe_name}.md").exists():
                    exists = True
                    break
            if exists:
                continue

            # 收集上下文
            ctx = concept_contexts.get(ref_name, [])
            ctx_text = "\n\n".join(c[:300] for c in ctx[:3]) if ctx else ""

            # LLM 生成完整概念页面
            page_body = ""
            page_type = "concept"
            category = "技术概念"

            if llm:
                try:
                    gen_prompt = f"为「{ref_name}」生成一个知识库概念页面。用中文。\n\n"
                    if ctx_text:
                        gen_prompt += (
                            f"以下是知识库文章中提到它的上下文：\n{ctx_text}\n\n"
                        )
                    gen_prompt += (
                        "请按以下格式输出（严格遵守）：\n\n"
                        "第一行必须是：type: concept 或 entity\n"
                        "第二行必须是：category: 分类名\n"
                        "（type: concept = 技术概念/方法论/架构模式/协议；"
                        "entity = 人物/公司/产品/工具/框架）\n"
                        "（category 可选：技术概念、方法论、架构模式、人物、公司、产品、框架、工具）\n\n"
                        "然后输出正文，必须包含以下章节：\n"
                        "## 定义\n"
                        "（2-3 句话清晰定义这个概念是什么）\n\n"
                        "## 核心要点\n"
                        "（3-5 个要点，每个 1-2 句话展开）\n\n"
                        "## 应用场景\n"
                        "（在什么场景下会用到，结合上下文）\n\n"
                        "## 相关概念\n"
                        "（列出相关的概念，用 [[双链]] 格式，如 [[Agent]]、[[RAG]]）\n\n"
                        "如果是人物/公司类实体，章节改为：定义、主要贡献、代表作品、相关概念。\n"
                        "用 [[双链]] 引用其他相关概念。"
                    )

                    result = await llm.chat(
                        system="你是一位专业的知识库编辑，擅长撰写准确、结构化的概念词条。",
                        user=gen_prompt,
                        max_tokens=2048,
                        temperature=0.3,
                    )

                    # 解析 type 和 category
                    import re as _re

                    lines = result.strip().split("\n")
                    body_start = 0
                    for i, line in enumerate(lines):
                        stripped = line.strip()
                        if stripped.startswith("type:"):
                            t = stripped[5:].strip().lower()
                            if t in ("entity", "concept"):
                                page_type = t
                            body_start = i + 1
                        elif stripped.startswith("category:"):
                            category = stripped[9:].strip()
                            body_start = i + 1
                        elif stripped.startswith("##"):
                            break
                    page_body = "\n".join(lines[body_start:]).strip()

                except Exception as e:
                    print(f"[vault] 概念 {ref_name} 生成失败: {e}")

            if not page_body:
                page_body = (
                    f"## 定义\n\n{ref_name} 是一个在知识库文章中被引用的概念。\n"
                )

            # 写入文件
            dir_name = "entities" if page_type == "entity" else "concepts"
            filepath = docs_dir / f"wiki/{dir_name}/{safe_name}.md"
            filepath.parent.mkdir(parents=True, exist_ok=True)

            source_name = source.split("/")[-1].replace(".md", "")
            tag_type = "entity" if page_type == "entity" else "concept"

            page_content = (
                f"---\n"
                f'title: "{ref_name}"\n'
                f"tags: [{tag_type}, {category}]\n"
                f"created: {today}\n"
                f"status: seedling\n"
                f"---\n\n"
                f"# {ref_name}\n\n"
                f"> {category}\n\n"
                f"{page_body}\n\n"
                f"## 相关文章\n\n"
                f"- [[{source_name}]]\n"
            )
            filepath.write_text(page_content, encoding="utf-8")
            created_count += 1
            print(f"[vault] 创建概念: {dir_name}/{safe_name}.md ({category})")

        print(f"[vault] 共创建 {created_count} 个概念/实体页面")

    async def refresh_concepts(self) -> str:
        """重新生成所有概念/实体页面：LLM 重写简介 + 分类，保留相关文章引用。"""
        import re
        from datetime import date

        docs_dir = self.config.docs_dir
        today = date.today().isoformat()

        # Step 1: 扫描所有文章，收集每个 [[双链]] 被哪些文章引用
        # ref_name → set of source_names
        ref_sources: dict[str, set[str]] = {}
        articles_dir = docs_dir / "wiki" / "articles"
        if articles_dir.exists():
            for md in articles_dir.rglob("*.md"):
                text = md.read_text(encoding="utf-8")
                source_name = md.stem
                for m in re.finditer(r"\[\[([^\]]+)\]\]", text):
                    ref_name = m.group(1).strip()
                    if ref_name and not _is_junk_concept(ref_name):
                        ref_sources.setdefault(ref_name, set()).add(source_name)

        if not ref_sources:
            return "没有找到任何 [[双链]] 引用"

        # Step 2: 删除旧的 concepts/ 和 entities/ 页面
        for dir_name in ("concepts", "entities"):
            d = docs_dir / "wiki" / dir_name
            if d.exists():
                for f in d.glob("*.md"):
                    f.unlink()

        # Step 3: 用 LLM 重新生成（带分类）
        concepts = []
        for ref_name, sources in ref_sources.items():
            safe_name = re.sub(r"[^\w\-]", "-", ref_name.lower())[:60].strip("-")
            if safe_name:
                # 取第一个来源作为 source（实际会在下面补全所有来源）
                concepts.append((ref_name, safe_name, ""))

        await self._create_concept_pages(docs_dir, concepts, today)

        # Step 4: 补全所有相关文章引用
        for ref_name, sources in ref_sources.items():
            safe_name = re.sub(r"[^\w\-]", "-", ref_name.lower())[:60].strip("-")
            if not safe_name:
                continue
            # 查找页面（可能在 concepts/ 或 entities/）
            filepath = None
            for dir_name in ("concepts", "entities"):
                p = docs_dir / f"wiki/{dir_name}/{safe_name}.md"
                if p.exists():
                    filepath = p
                    break
            if not filepath:
                continue

            text = filepath.read_text(encoding="utf-8")
            # 确保有相关文章章节
            if "## 相关文章" not in text:
                text = text.rstrip() + "\n\n## 相关文章\n\n"
            # 追加所有来源
            for src in sorted(sources):
                link = f"[[{src}]]"
                if link not in text:
                    text = text.rstrip() + f"\n- {link}\n"
            filepath.write_text(text, encoding="utf-8")

        self.index.refresh()
        total = len(
            [
                p
                for d in ("concepts", "entities")
                for p in (docs_dir / "wiki" / d).glob("*.md")
                if (docs_dir / "wiki" / d).exists()
            ]
        )
        return f"已重新生成 {total} 个概念/实体页面，从 {len(ref_sources)} 个 [[双链]] 引用中提取"

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

    def delete_page(self, file_path: str) -> str:
        """删除 wiki 页面。

        Args:
            file_path: 相对于 docs 的路径（如 wiki/articles/xxx.md）

        Returns:
            删除结果文本
        """
        # 安全检查：只允许删除 wiki/ 下的文件
        if not file_path.startswith("wiki/"):
            return f"安全限制: 只能删除 wiki/ 下的文件，不能删除 {file_path}"

        full_path = self.config.docs_dir / file_path
        if not full_path.exists():
            return f"文件不存在: {file_path}"

        full_path.unlink()
        self.index.refresh()
        return f"已删除: {file_path}"

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

    async def ask(self, message: str, on_step=None, user_id: str = "") -> str:
        """用自然语言和知识库交互（通过 Agent）。

        这是最高层的接口。用户说一句话，Agent 自己决定做什么。

        Args:
            message: 用户输入
            user_id: 用户标识（用于持久化会话记忆）

        Returns:
            Agent 的回复
        """
        agent = self.create_agent(on_step=on_step)
        return await agent.run(message, user_id=user_id)

    # ── 状态 ──

    def status(self) -> dict:
        """返回知识库状态信息。"""
        import os

        self.ensure_indexed()
        sources = self.index.get_all_sources()
        skill_count = len(self.skill_registry.actions) if self._skills_loaded else 0

        # 飞书通道状态
        feishu_app_id = os.getenv("AKASHA_FEISHU_APP_ID", "")
        feishu_configured = bool(
            feishu_app_id and os.getenv("AKASHA_FEISHU_APP_SECRET", "")
        )

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
            "feishu_configured": feishu_configured,
            "feishu_bot_name": os.getenv("AKASHA_FEISHU_BOT_NAME", "Akasha")
            if feishu_configured
            else None,
        }

    def status_formatted(self) -> str:
        """返回格式化的状态文本。"""
        s = self.status()
        lines = [
            "",
            "=== Akasha 状态 ===",
            "",
            f"  知识库:    {s['vault_path']}",
            f"  文档目录:  {s['docs_dir']}",
            f"  向量库:    {s['chroma_dir']}",
            f"  Embedding: ChromaDB 内置 (all-MiniLM-L6-v2, 本地)",
            f"  已索引:    {s['files_count']} 个文件, {s['chunks_count']} 个 chunks",
        ]
        if s["skills_count"]:
            lines.append(f"  Skills:    {s['skills_count']} 个 tool 已注册")

        # LLM 状态
        lines.append("")
        lines.append("--- LLM ---")
        if s["llm_configured"]:
            lines.append(f"  状态:      已配置 ✓")
            lines.append(f"  Provider:  {s['llm_provider']}")
            lines.append(f"  模型:      {s['llm_model']}")
            lines.append(f"  端点:      {s['llm_base_url']}")
        else:
            lines.append(f"  状态:      未配置 ✗")
            lines.append(f"  影响:      ingest / save / ask 不可用，搜索正常")
            lines.append(f"  配置方法:")
            lines.append(f'    export AKASHA_LLM_API_KEY="sk-xxx"')
            lines.append(f'    export AKASHA_LLM_PROVIDER="openai"  # 或 anthropic')
            lines.append(f'    export AKASHA_LLM_MODEL="gpt-4o"    # 可选')

        # 飞书通道状态
        lines.append("")
        lines.append("--- 飞书通道 ---")
        if s["feishu_configured"]:
            lines.append(f"  状态:      已配置 ✓")
            lines.append(f"  Bot:       {s['feishu_bot_name']}")
        else:
            lines.append(f"  状态:      未配置 ✗")
            lines.append(f"  配置方法:")
            lines.append(f'    export AKASHA_FEISHU_APP_ID="cli_xxx"')
            lines.append(f'    export AKASHA_FEISHU_APP_SECRET="xxx"')

        lines.append("")
        return "\n".join(lines)


# ---------------------------------------------------------------------------
# 概念过滤
# ---------------------------------------------------------------------------

# 垃圾概念黑名单（网站导航、平台名、广告等）
_JUNK_CONCEPTS = {
    # 平台/网站
    "百家号",
    "百度",
    "百度开放平台",
    "百度百科",
    "知乎",
    "微信",
    "微博",
    "今日头条",
    "抖音",
    "bilibili",
    "b站",
    "youtube",
    "twitter",
    "x.com",
    "github",
    "gitee",
    "csdn",
    "掘金",
    "简书",
    "博客园",
    "cnblogs",
    "stackoverflow",
    "medium",
    "substack",
    # 网页元素
    "首页",
    "登录",
    "注册",
    "关于我们",
    "联系我们",
    "隐私政策",
    "用户协议",
    "评论",
    "分享",
    "收藏",
    "点赞",
    "关注",
    "订阅",
    "更多",
    "上一篇",
    "下一篇",
    "相关推荐",
    "热门文章",
    "最新文章",
    # 太泛的词
    "技术",
    "文章",
    "视频",
    "链接",
    "内容",
    "原文",
    "来源",
    "作者",
}

# 长度太短或太长的不要
_MIN_CONCEPT_LEN = 2
_MAX_CONCEPT_LEN = 30


def _is_junk_concept(name: str) -> bool:
    """判断是否是垃圾概念。"""
    name_lower = name.strip().lower()

    # 黑名单
    if name_lower in _JUNK_CONCEPTS or name in _JUNK_CONCEPTS:
        return True

    # 长度
    if len(name.strip()) < _MIN_CONCEPT_LEN or len(name.strip()) > _MAX_CONCEPT_LEN:
        return True

    # 纯数字 / 纯符号
    import re

    if re.match(r"^[\d\s\-_.]+$", name):
        return True

    # URL
    if name.startswith("http") or name.startswith("www."):
        return True

    # 中英文混合（如 "AWQ量化"、"Agent架构"）→ 应该纯英文或纯中文
    has_chinese = bool(re.search(r"[\u4e00-\u9fff]", name))
    has_english = bool(re.search(r"[a-zA-Z]", name))
    if has_chinese and has_english:
        return True

    return False
