"""
知识摄入器 — Karpathy LLM Wiki 核心。

不只是索引，而是编译知识:
- ingest: 读原始源 → LLM 提取概念/实体 → 创建/更新 wiki 页面
- save_as_page: 好回答存为 wiki 页
- lint: wiki 健康检查
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

from .config import Config
from .llm import LLMClient


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
# Ingester
# ---------------------------------------------------------------------------


class Ingester:
    """知识摄入器。"""

    def __init__(self, config: Config, llm: LLMClient):
        self.config = config
        self.llm = llm

    async def ingest(self, source_path: str) -> IngestResult:
        """摄入单个源文件 → 提取知识 → 创建/更新 wiki 页面。

        Args:
            source_path: 相对于 vault 的路径（如 raw/analysis/autoagent-analysis.md）

        Returns:
            IngestResult
        """
        full_path = self.config.docs_dir / source_path
        if not full_path.exists():
            raise FileNotFoundError(f"源文件不存在: {source_path}")

        content = full_path.read_text(encoding="utf-8")
        result = IngestResult(source_file=source_path)

        # 读取 schema 规则
        schema = ""
        if self.config.schema_path.exists():
            schema = self.config.schema_path.read_text(encoding="utf-8")

        # 收集已有 wiki 页面信息（供 LLM 判断是创建还是合并）
        existing_pages = self._list_wiki_pages()
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

        # 解析 JSON 响应
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

            # L4 安全: 校验写入路径
            if not self._validate_write_path(page_path):
                continue

            full_page_path = self.config.docs_dir / page_path

            if full_page_path.exists():
                # 合并到已有页面
                existing_content = full_page_path.read_text(encoding="utf-8")
                merged = await self._merge_page(
                    existing_content, page_content, source_path
                )
                full_page_path.write_text(merged, encoding="utf-8")
                result.pages_updated.append(page_path)
            else:
                # 创建新页面
                full_page_path.parent.mkdir(parents=True, exist_ok=True)
                full_page_path.write_text(page_content, encoding="utf-8")
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
        # L4 安全: 校验 category
        valid_categories = {"concepts", "entities", "comparisons", "synthesis"}
        if category not in valid_categories:
            raise ValueError(f"无效分类: {category}")

        # 生成文件名
        filename = re.sub(r"[^\w\s-]", "", title.lower())
        filename = re.sub(r"[\s]+", "-", filename).strip("-")
        page_path = f"wiki/{category}/{filename}.md"
        full_path = self.config.docs_dir / page_path

        # LLM 整理为 wiki 格式
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

        full_path.parent.mkdir(parents=True, exist_ok=True)
        full_path.write_text(formatted, encoding="utf-8")

        # 更新 index 和 log
        result = IngestResult(
            source_file="(对话生成)",
            pages_created=[page_path],
            concepts_extracted=[title],
        )
        self._update_index(result)
        self._append_log(result)

        return page_path

    def lint(self) -> list[LintIssue]:
        """Wiki 健康检查（不需要 LLM，纯规则检查）。

        检查:
        - 缺失 frontmatter
        - 孤立页面（没有被其他页面引用）
        - 链接过少（< 2 个 related）
        - 空页面
        """
        issues: list[LintIssue] = []
        wiki_dir = self.config.wiki_dir
        if not wiki_dir.exists():
            return issues

        all_pages: dict[str, str] = {}  # {相对路径: 内容}
        for md in wiki_dir.rglob("*.md"):
            rel = str(md.relative_to(self.config.docs_dir))
            try:
                all_pages[rel] = md.read_text(encoding="utf-8")
            except (UnicodeDecodeError, OSError):
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

            # 检查: 空页面
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

            # 检查: 缺失 frontmatter
            if not content.strip().startswith("---"):
                issues.append(
                    LintIssue(
                        type="missing_frontmatter",
                        page=page_path,
                        description="缺少 YAML frontmatter",
                        suggestion="添加 title, tags, sources, related, created, updated, status",
                    )
                )

            # 检查: 孤立页面（没有其他页面通过 [[]] 引用它）
            if page_name not in all_links:
                issues.append(
                    LintIssue(
                        type="orphan",
                        page=page_path,
                        description="没有其他页面引用该页面",
                        suggestion=f"在相关页面中添加 [[{page_name}]] 引用",
                    )
                )

            # 检查: [[]] 引用过少
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

    def _validate_write_path(self, page_path: str) -> bool:
        """L4 安全: 校验写入路径。

        规则:
        - 必须以 wiki/ 开头（不允许写 raw/、schema.md、index.md 等）
        - 不允许包含 .. 路径穿越
        - resolve 后必须在 wiki_dir 内
        """
        from .events import emit, SECURITY_BLOCKED

        if ".." in page_path:
            emit(SECURITY_BLOCKED, reason="path_traversal", path=page_path)
            return False

        if not page_path.startswith("wiki/"):
            emit(SECURITY_BLOCKED, reason="write_outside_wiki", path=page_path)
            return False

        # resolve 验证
        full_path = (self.config.docs_dir / page_path).resolve()
        wiki_dir = self.config.wiki_dir.resolve()
        if not str(full_path).startswith(str(wiki_dir) + "/") and full_path != wiki_dir:
            emit(SECURITY_BLOCKED, reason="path_escape", path=page_path)
            return False

        return True

    async def _merge_page(
        self,
        existing_content: str,
        new_content: str,
        source_path: str,
    ) -> str:
        """合并新信息到已有页面。"""
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

    def _list_wiki_pages(self) -> list[str]:
        """列出所有已有 wiki 页面。"""
        wiki_dir = self.config.wiki_dir
        if not wiki_dir.exists():
            return []
        pages = []
        for md in wiki_dir.rglob("*.md"):
            pages.append(str(md.relative_to(self.config.docs_dir)))
        return sorted(pages)

    def _update_index(self, result: IngestResult) -> None:
        """更新 index.md — 追加新创建的页面条目。"""
        index_path = self.config.index_path
        if not index_path.exists():
            return

        content = index_path.read_text(encoding="utf-8")

        for page_path in result.pages_created:
            # 解析分类和标题
            parts = page_path.split("/")
            if len(parts) >= 3:
                category = parts[1]  # concepts / entities / ...
                page_name = Path(parts[-1]).stem
                title = page_name.replace("-", " ").title()

                # 找到对应分类的锚点，追加条目
                section_map = {
                    "concepts": "## 概念 (concepts/)",
                    "entities": "## 实体 (entities/)",
                    "comparisons": "## 对比 (comparisons/)",
                    "synthesis": "## 综合 (synthesis/)",
                }
                section_header = section_map.get(category)
                if section_header and section_header in content:
                    # 去掉"暂无条目"占位符
                    placeholder = f"{section_header}\n\n*暂无条目"
                    if placeholder in content:
                        content = content.replace(
                            placeholder,
                            f"{section_header}\n\n- [[{page_name}]] — {title}",
                        )
                    else:
                        # 在该分类末尾追加
                        content = content.replace(
                            section_header,
                            f"{section_header}\n- [[{page_name}]] — {title}",
                        )

        index_path.write_text(content, encoding="utf-8")

    def _append_log(self, result: IngestResult) -> None:
        """追加 log.md。"""
        log_path = self.config.log_path
        if not log_path.exists():
            return

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

        content = log_path.read_text(encoding="utf-8")
        content += "\n".join(lines) + "\n"
        log_path.write_text(content, encoding="utf-8")

    @staticmethod
    def _parse_json_response(text: str) -> dict | None:
        """从 LLM 响应中解析 JSON（容忍 markdown code block 包裹）。"""
        # 尝试直接解析
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            pass

        # 尝试从 ```json ... ``` 中提取
        m = re.search(r"```(?:json)?\s*\n?(.*?)\n?```", text, re.DOTALL)
        if m:
            try:
                return json.loads(m.group(1))
            except json.JSONDecodeError:
                pass

        # 尝试找到第一个 { 和最后一个 }
        start = text.find("{")
        end = text.rfind("}")
        if start != -1 and end != -1 and end > start:
            try:
                return json.loads(text[start : end + 1])
            except json.JSONDecodeError:
                pass

        return None
