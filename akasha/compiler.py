"""
知识编译器 — Karpathy LLM Wiki 核心。

不只是索引，而是编译知识:
- ingest: 读原始源 → LLM 提取概念/实体 → 创建/更新 wiki 页面
- save_as_page: 好回答存为 wiki 页
- lint: wiki 健康检查

依赖 FileStore 做文件操作（不直接碰文件系统），
依赖 LLMClient 做 LLM 调用。
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

from .config import Config
from .llm import LLMClient
from .storage.files import FileStore


# ---------------------------------------------------------------------------
# 数据结构
# ---------------------------------------------------------------------------


@dataclass
class IngestResult:
    source_file: str
    pages_created: list[str] = field(default_factory=list)
    pages_updated: list[str] = field(default_factory=list)
    concepts_extracted: list[str] = field(default_factory=list)

    def summary(self) -> str:
        parts = [f"摄入完成: {self.source_file}"]
        if self.concepts_extracted:
            parts.append(f"  提取概念: {', '.join(self.concepts_extracted)}")
        if self.pages_created:
            parts.append(f"  创建页面: {', '.join(self.pages_created)}")
        if self.pages_updated:
            parts.append(f"  更新页面: {', '.join(self.pages_updated)}")
        return "\n".join(parts)


@dataclass
class LintIssue:
    type: str  # orphan / missing_frontmatter / few_links / empty
    page: str
    description: str
    suggestion: str

    def __str__(self) -> str:
        return f"[{self.type}] {self.page}: {self.description} → {self.suggestion}"


# ---------------------------------------------------------------------------
# Prompts
# ---------------------------------------------------------------------------

EXTRACT_PROMPT = """\
你是一个知识库管理助手。你的任务是从源文件中提取关键知识，生成结构化的 wiki 页面。

## 规则
1. 从源文件中识别出所有重要的 **概念** 和 **实体**
2. 为每个概念/实体生成一个独立的 wiki 页面
3. 页面之间通过 [[双链]] 互相引用
4. 每个页面必须有完整的 YAML frontmatter
5. 文件名用小写+连字符，如 agent-loop.md
6. 概念放 concepts/，实体放 entities/，对比放 comparisons/

## 输出格式
输出一个 JSON 对象，包含:
```json
{
  "concepts": ["概念1", "概念2"],
  "pages": [
    {
      "path": "wiki/concepts/agent-loop.md",
      "content": "---\\ntitle: Agent Loop\\ntags: [agent, design-pattern]\\n...\\n---\\n\\n# Agent Loop\\n\\n..."
    }
  ]
}
```

注意:
- content 中的 frontmatter 必须包含: title, tags, sources, related, created, updated, status
- sources 列出原始源文件的相对路径
- related 列出相关 wiki 页面路径（使用 wiki/ 前缀）
- status 新页面统一用 seedling
- 内容要精炼有结构，不要照搬原文
"""

MERGE_PROMPT = """\
你是一个知识库管理助手。你需要将新信息合并到已有的 wiki 页面中。

## 规则
1. 保留已有内容，不要删除
2. 将新信息整合到合适的章节
3. 如果新旧信息矛盾，用 `> [!warning] 信息矛盾` 标注
4. 更新 frontmatter 中的 sources（追加新源）、updated（今天日期）、related（新关联）
5. 如果 status 是 seedling 且信息变丰富了，可以升级为 developing

## 输出
直接输出合并后的完整 Markdown 页面内容（包含 frontmatter）。不要输出其他内容。
"""

SAVE_PAGE_PROMPT = """\
你是一个知识库管理助手。你需要将一段内容整理为一个 wiki 页面。

## 规则
1. 添加完整的 YAML frontmatter (title, tags, sources, related, created, updated, status)
2. 内容结构化，使用标题层级
3. 适当添加 [[双链]] 引用其他可能存在的概念
4. status 设为 seedling
5. sources 设为空列表（因为是对话生成的）

## 输出
直接输出完整的 Markdown 页面内容（包含 frontmatter）。不要输出其他内容。
"""


# ---------------------------------------------------------------------------
# Compiler
# ---------------------------------------------------------------------------


class Compiler:
    """知识编译器。"""

    def __init__(self, config: Config, files: FileStore, llm: LLMClient):
        self.config = config
        self.files = files
        self.llm = llm

    async def ingest(self, source_path: str) -> IngestResult:
        """摄入单个源文件 → 提取知识 → 创建/更新 wiki 页面。

        Args:
            source_path: 相对于 docs 的路径（如 raw/analysis/xxx.md）

        Returns:
            IngestResult
        """
        content = self.files.read_raw(source_path)
        result = IngestResult(source_file=source_path)

        # 读取 schema 规则
        schema = ""
        if self.config.schema_path.exists():
            schema = self.config.schema_path.read_text(encoding="utf-8")

        # 已有 wiki 页面
        existing_pages = self.files.list_wiki_pages()
        existing_info = (
            "\n".join(f"- {p}" for p in existing_pages)
            if existing_pages
            else "（暂无已有页面）"
        )

        # Step 1: LLM 提取概念和生成页面
        user_msg = (
            f"## 源文件路径\n{source_path}\n\n"
            f"## 源文件内容\n```\n{content[:15000]}\n```\n\n"
            f"## 已有 wiki 页面\n{existing_info}\n\n"
            f"## Schema 规则\n{schema[:3000]}\n\n"
            f"请提取关键概念和实体，生成 wiki 页面。今天日期: {date.today().isoformat()}"
        )

        raw_response = await self.llm.chat(
            system=EXTRACT_PROMPT,
            user=user_msg,
            temperature=0.3,
            max_tokens=8192,
        )

        parsed = self._parse_json_response(raw_response)
        if not parsed:
            return result

        result.concepts_extracted = parsed.get("concepts", [])

        # Step 2: 写入或合并 wiki 页面
        for page_info in parsed.get("pages", []):
            page_path = page_info.get("path", "")
            page_content = page_info.get("content", "")
            if not page_path or not page_content:
                continue

            # 安全校验（write_wiki 内部会做）
            if not page_path.startswith("wiki/") or ".." in page_path:
                continue

            full_page_path = self.config.docs_dir / page_path

            if full_page_path.exists():
                # 合并到已有页面
                existing_content = self.files.read_raw(page_path)
                merged = await self._merge_page(
                    existing_content, page_content, source_path
                )
                self.files.write_wiki(page_path, merged)
                result.pages_updated.append(page_path)
            else:
                # 创建新页面
                self.files.write_wiki(page_path, page_content)
                result.pages_created.append(page_path)

        # Step 3: 更新 index.md 和 log.md
        self._update_index(result)
        self._append_log(result)

        return result

    async def save_as_page(
        self,
        title: str,
        content: str,
        category: str = "synthesis",
    ) -> str:
        """将内容存为 wiki 页面。

        Args:
            title: 页面标题
            content: 页面内容
            category: 分类 (concepts/entities/comparisons/synthesis)

        Returns:
            创建的页面路径
        """
        valid_categories = {"concepts", "entities", "comparisons", "synthesis"}
        if category not in valid_categories:
            raise ValueError(f"无效分类: {category}")

        filename = re.sub(r"[^\w\s-]", "", title.lower())
        filename = re.sub(r"[\s]+", "-", filename).strip("-")
        page_path = f"wiki/{category}/{filename}.md"

        user_msg = (
            f"## 标题\n{title}\n\n"
            f"## 分类\n{category}\n\n"
            f"## 原始内容\n{content[:10000]}\n\n"
            f"今天日期: {date.today().isoformat()}"
        )

        formatted = await self.llm.chat(
            system=SAVE_PAGE_PROMPT,
            user=user_msg,
            temperature=0.3,
            max_tokens=4096,
        )

        self.files.write_wiki(page_path, formatted)

        result = IngestResult(
            source_file="(对话生成)",
            pages_created=[page_path],
            concepts_extracted=[title],
        )
        self._update_index(result)
        self._append_log(result)

        return page_path

    def lint(self) -> list[LintIssue]:
        """Wiki 健康检查（不需要 LLM，纯规则检查）。"""
        issues: list[LintIssue] = []
        wiki_pages = self.files.list_wiki_pages()
        if not wiki_pages:
            return issues

        all_pages: dict[str, str] = {}
        for page_path in wiki_pages:
            try:
                all_pages[page_path] = self.files.read_raw(page_path)
            except (FileNotFoundError, ValueError):
                continue

        if not all_pages:
            return issues

        # 收集所有 [[双链]] 引用
        all_links: set[str] = set()
        for content in all_pages.values():
            links = re.findall(r"\[\[([^\]]+)\]\]", content)
            all_links.update(links)

        for page_path, content in all_pages.items():
            page_name = Path(page_path).stem

            # 空页面
            if len(content.strip()) < 50:
                issues.append(
                    LintIssue(
                        type="empty",
                        page=page_path,
                        description="页面内容过少（< 50 字符）",
                        suggestion="补充内容或删除该页面",
                    )
                )
                continue

            # 缺失 frontmatter
            if not content.strip().startswith("---"):
                issues.append(
                    LintIssue(
                        type="missing_frontmatter",
                        page=page_path,
                        description="缺少 YAML frontmatter",
                        suggestion="添加 title, tags, sources, related, created, updated, status",
                    )
                )

            # 孤立页面
            if page_name not in all_links:
                issues.append(
                    LintIssue(
                        type="orphan",
                        page=page_path,
                        description="没有其他页面引用该页面",
                        suggestion=f"在相关页面中添加 [[{page_name}]] 引用",
                    )
                )

            # 引用过少
            own_links = re.findall(r"\[\[([^\]]+)\]\]", content)
            if len(own_links) < 2:
                issues.append(
                    LintIssue(
                        type="few_links",
                        page=page_path,
                        description=f"只有 {len(own_links)} 个 [[双链]] 引用（最少需要 2 个）",
                        suggestion="添加更多相关页面的 [[双链]] 引用",
                    )
                )

        return issues

    # ── 内部方法 ──

    async def _merge_page(
        self,
        existing_content: str,
        new_content: str,
        source_path: str,
    ) -> str:
        user_msg = (
            f"## 已有页面内容\n```\n{existing_content[:8000]}\n```\n\n"
            f"## 新信息（来自 {source_path}）\n```\n{new_content[:8000]}\n```\n\n"
            f"请将新信息合并到已有页面。今天日期: {date.today().isoformat()}"
        )
        return await self.llm.chat(
            system=MERGE_PROMPT,
            user=user_msg,
            temperature=0.2,
            max_tokens=8192,
        )

    def _update_index(self, result: IngestResult) -> None:
        """根据 wiki/ 目录实际内容重新生成 index.md。"""
        self.rebuild_index()

    def rebuild_index(self) -> None:
        """全量扫描 wiki/ 目录，重新生成首页。"""
        wiki_dir = self.config.wiki_dir

        categories = [
            ("articles", "文章", []),
            ("concepts", "概念", []),
            ("entities", "实体", []),
            ("synthesis", "综合", []),
            ("comparisons", "对比", []),
        ]

        all_pages = []

        for cat_dir_name, cat_label, items in categories:
            cat_dir = wiki_dir / cat_dir_name
            if not cat_dir.exists():
                continue
            for md_file in sorted(cat_dir.glob("*.md")):
                title = self._extract_title_from_file(md_file)
                rel_path = f"wiki/{cat_dir_name}/{md_file.name}"
                mtime = md_file.stat().st_mtime
                items.append((title, rel_path, mtime))
                all_pages.append((title, rel_path, mtime, cat_label))

        total_pages = len(all_pages)
        recent = sorted(all_pages, key=lambda x: x[2], reverse=True)[:8]

        # 构建饼图数据
        pie_items = []
        for _, cat_label, items in categories:
            if items:
                pie_items.append(f'    "{cat_label}" : {len(items)}')

        lines = [
            "---",
            "hide:",
            "  - navigation",
            "---",
            "",
            "# Akasha 知识库",
            "",
            "Akasha 是一个**个人 AI 知识库引擎**。",
            "通过飞书、MCP 或命令行发送视频链接、网页、文档，",
            "Akasha 会自动下载、转写、分析，",
            "用 LLM 提取关键知识并整理成结构化文档。",
            "",
            "本站点由 Akasha 基于知识库内容自动生成，使用 MkDocs Material 渲染。",
            "",
            "---",
            "",
            f"## 知识库概览 · 共 {total_pages} 篇",
            "",
            "```mermaid",
            "pie showData",
            "    title 内容分布",
        ]
        lines.extend(pie_items)
        lines.append("```")
        lines.append("")

        # 分类统计表格
        lines.append("| 分类 | 数量 | 说明 |")
        lines.append("|:-----|:----:|:-----|")
        cat_desc = {
            "文章": "视频、网页等外部内容生成的知识文档",
            "概念": "从文章中提取的概念词条",
            "实体": "具体的项目、人物、工具等实体记录",
            "综合": "Agent 对话中产生的总结和指南",
            "对比": "不同方案/工具的对比分析",
        }
        for _, cat_label, items in categories:
            count = len(items)
            desc = cat_desc.get(cat_label, "")
            lines.append(f"| **{cat_label}** | {count} | {desc} |")
        lines.append("")

        # 最近更新
        if recent:
            lines.append("## 最近更新")
            lines.append("")
            lines.append("| 标题 | 分类 | 日期 |")
            lines.append("|:-----|:----:|:----:|")
            for title, rel_path, mtime, cat_label in recent:
                from datetime import datetime

                date_str = datetime.fromtimestamp(mtime).strftime("%Y-%m-%d")
                display_title = title if len(title) <= 35 else title[:32] + "..."
                lines.append(
                    f"| [{display_title}]({rel_path}) | {cat_label} | {date_str} |"
                )
            lines.append("")

        # 页脚
        lines.append("---")
        lines.append(
            "<small>"
            "由 [Akasha](https://github.com/m17y/akasha) 自动生成 · "
            "语义搜索 + LLM 知识编译 + Agent"
            "</small>"
        )

        self.config.index_path.write_text("\n".join(lines), encoding="utf-8")

    @staticmethod
    def _extract_title_from_file(md_path: Path) -> str:
        """从 Markdown 文件提取标题。"""
        try:
            text = md_path.read_text(encoding="utf-8")
            # frontmatter title
            if text.startswith("---"):
                parts = text.split("---", 2)
                if len(parts) >= 3:
                    for line in parts[1].strip().split("\n"):
                        line = line.strip()
                        if line.startswith("title:"):
                            title = line[6:].strip().strip('"').strip("'")
                            if title:
                                return title
            # 第一个 # 标题
            for line in text.split("\n")[:20]:
                line = line.strip()
                if line.startswith("# ") and not line.startswith("##"):
                    return line[2:].strip()
        except (UnicodeDecodeError, OSError):
            pass
        return md_path.stem.replace("-", " ").title()

    def _append_log(self, result: IngestResult) -> None:
        """追加 log.md。"""
        today = date.today().isoformat()
        lines = [f"\n## {today}"]

        if result.pages_created or result.pages_updated:
            action = "ingest" if "raw/" in result.source_file else "save_as_page"
            lines.append(f"- **{action}** {result.source_file}")
            if result.pages_created:
                lines.append(f"  - 创建: {', '.join(result.pages_created)}")
            if result.pages_updated:
                lines.append(f"  - 更新: {', '.join(result.pages_updated)}")
            if result.concepts_extracted:
                lines.append(f"  - 提取概念: {', '.join(result.concepts_extracted)}")

        self.files.append_file("log.md", "\n".join(lines) + "\n")

    @staticmethod
    def _parse_json_response(text: str) -> dict | None:
        """从 LLM 响应中解析 JSON。"""
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            pass

        m = re.search(r"```(?:json)?\s*\n?(.*?)\n?```", text, re.DOTALL)
        if m:
            try:
                return json.loads(m.group(1))
            except json.JSONDecodeError:
                pass

        start = text.find("{")
        end = text.rfind("}")
        if start != -1 and end != -1 and end > start:
            try:
                return json.loads(text[start : end + 1])
            except json.JSONDecodeError:
                pass

        return None
