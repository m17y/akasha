"""
PDF Skill 执行层。

提取 PDF 文本 → LLM 深度整理 → 保存为 wiki 页面。
使用 pymupdf (fitz) 提取文本，fallback 到 pdfplumber。
"""

from __future__ import annotations

import re
from datetime import date
from pathlib import Path


class PDFExecutor:
    """PDF 处理执行器。"""

    async def extract(self, file_path: str) -> str:
        """提取 PDF 文本内容。"""
        path = Path(file_path)
        if not path.exists():
            return f"文件不存在: {file_path}"

        text = self._extract_text(path)
        if not text.strip():
            return "PDF 内容为空或无法提取文本"
        return text

    async def to_wiki(self, file_path: str, docs_dir: Path | None = None) -> str:
        """提取 PDF 内容并生成 wiki 页面。"""
        path = Path(file_path)
        if not path.exists():
            return f"文件不存在: {file_path}"

        # Step 1: 提取文本
        text = self._extract_text(path)
        if not text.strip():
            return "PDF 内容为空或无法提取文本"

        # Step 2: 获取标题
        title = path.stem.replace("-", " ").replace("_", " ")
        # 从文本前几行提取可能的标题
        first_lines = text.strip().split("\n")[:5]
        for line in first_lines:
            line = line.strip()
            if len(line) > 5 and len(line) < 100:
                title = line
                break

        safe_title = re.sub(r"[^\w\-]", "-", title.lower())[:40].strip("-") or "pdf"
        display_title = title if len(title) <= 30 else title[:27] + "..."

        # Step 3: LLM 深度整理
        analysis = await self._analyze_content(title, text)

        # Step 4: 生成 wiki 页面
        today = date.today().isoformat()
        filename = f"{safe_title}.md"
        rel_path = f"wiki/articles/{filename}"

        content = (
            f"---\n"
            f'title: "{display_title}"\n'
            f"tags: [pdf]\n"
            f'source: "{path.name}"\n'
            f"created: {today}\n"
            f"updated: {today}\n"
            f"status: {'developing' if analysis else 'seedling'}\n"
            f"---\n\n"
            f"# {display_title}\n\n"
            f"> 来源: PDF 文件 `{path.name}`\n\n"
        )

        if analysis:
            content += analysis + "\n"
        else:
            # fallback: 直接放文本摘要
            content += f"## 内容摘要\n\n{text[:2000]}\n"

        if docs_dir:
            filepath = docs_dir / rel_path
            filepath.parent.mkdir(parents=True, exist_ok=True)
            filepath.write_text(content, encoding="utf-8")

        return rel_path

    def _extract_text(self, path: Path) -> str:
        """从 PDF 提取文本。优先 pymupdf，fallback pdfplumber。"""
        # 方案 1: pymupdf (fitz)
        try:
            import fitz  # pymupdf

            doc = fitz.open(str(path))
            pages = []
            for page in doc:
                pages.append(page.get_text())
            doc.close()
            text = "\n\n".join(pages)
            if text.strip():
                return text
        except ImportError:
            pass
        except Exception:
            pass

        # 方案 2: pdfplumber
        try:
            import pdfplumber

            with pdfplumber.open(str(path)) as pdf:
                pages = []
                for page in pdf.pages:
                    t = page.extract_text()
                    if t:
                        pages.append(t)
                return "\n\n".join(pages)
        except ImportError:
            pass
        except Exception:
            pass

        return "(无法提取 PDF 文本，请安装 pymupdf 或 pdfplumber)"

    async def _analyze_content(self, title: str, text: str) -> str:
        """用 LLM 深度整理 PDF 内容。"""
        try:
            from akasha import _get_llm_client

            llm = _get_llm_client()
            if llm is None:
                return ""

            system_prompt = (
                "你是一位专业的知识提取专家，擅长从技术文档、论文、报告中提炼核心知识。\n"
                "用户给你一份 PDF 文档的提取文本（这是原始素材），"
                "你的任务是**提取知识**，不是转述原文。\n\n"
                "## 知识提取要求\n"
                "1. 直接输出 Markdown 内容，不要输出 frontmatter\n"
                "2. 用 ## 开头的章节组织内容\n"
                "3. 必须包含以下章节：\n"
                "   - ## 核心知识（从文档中提取的最重要的知识点，每个用 1-2 段话深入解释，"
                "不是摘要，而是你真正理解后的知识输出）\n"
                "   - ## 关键概念解析（文档中出现的重要概念，每个给出定义和在本文中的含义，"
                "用 [[双链]] 格式引用）\n"
                "   - ## 方法论与模式（如果文档涉及方法论、设计模式、最佳实践，"
                "提炼为可复用的知识）\n"
                "   - ## 数据与结论（关键数据、实验结果、作者结论，保留具体数字）\n"
                "   - ## 实践指南（基于文档知识，给出可操作的实践建议）\n"
                "   - ## 知识图谱（列出所有提取的概念和它们的关系，用 [[双链]] 格式）\n"
                "4. 如果有代码、公式、架构图描述，保留并解释\n"
                "5. **不要**转述原文结构，要按知识逻辑重新组织\n"
                "6. **提取**而非**翻译**——用你的理解重新表达，使知识可独立阅读\n"
                "7. [[双链]] 统一用英文名，如 [[Agent]] 不是 [[智能体]]\n"
                "8. [[双链]] 只放有知识价值的概念，不放网站名、平台名\n"
                "9. 用中文输出"
            )

            user_msg = (
                f"## 文档信息\n"
                f"- 标题: {title}\n\n"
                f"## 文档内容\n\n{text[:30000]}\n\n"
                f"请深度整理为知识文章。"
            )

            return await llm.chat(
                system=system_prompt,
                user=user_msg,
                max_tokens=8192,
                temperature=0.3,
            )
        except Exception as e:
            import sys

            print(f"[pdf] LLM 分析失败: {e}", file=sys.stderr)
            return ""


def get_executor() -> PDFExecutor:
    """工厂函数。"""
    return PDFExecutor()
