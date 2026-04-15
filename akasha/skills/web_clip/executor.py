"""
Web Clip Skill 执行层。

提取网页正文 → 转 Markdown → 保存为 wiki 页面。
不依赖外部库（trafilatura/readability），用内置的标签权重算法提取正文。
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urlparse, unquote, parse_qs

import httpx


# ---------------------------------------------------------------------------
# URL 解包
# ---------------------------------------------------------------------------

_REDIRECT_HOSTS = {
    "security.feishu.cn",
    "link.zhihu.com",
    "weixin110.qq.com",
}


def _unwrap_url(url: str) -> str:
    """从飞书/微信/知乎安全跳转链接中提取真实 URL。"""
    try:
        parsed = urlparse(url)
        if parsed.hostname in _REDIRECT_HOSTS:
            params = parse_qs(parsed.query)
            target = params.get("target", [None])[0]
            if target:
                return unquote(target)
    except Exception:
        pass
    return url


# ---------------------------------------------------------------------------
# HTML → 正文提取 → Markdown
# ---------------------------------------------------------------------------


@dataclass
class WebPage:
    """提取后的网页数据。"""

    url: str = ""
    title: str = ""
    content: str = ""  # Markdown 格式
    domain: str = ""

    def to_summary(self) -> str:
        parts = [f"**{self.title}**\n"]
        parts.append(f"- 来源: {self.url}")
        parts.append(f"- 域名: {self.domain}")
        parts.append(f"- 内容长度: {len(self.content)} 字符")
        if self.content:
            preview = self.content[:200]
            if len(self.content) > 200:
                preview += "..."
            parts.append(f"- 预览: {preview}")
        return "\n".join(parts)


class _HTMLTextExtractor(HTMLParser):
    """从 HTML 中提取正文并转换为 Markdown。

    策略：
    - 跳过 script/style/nav/header/footer/aside 等非正文标签
    - 保留 h1-h6 → Markdown 标题
    - 保留 p → 段落
    - 保留 li → 列表项
    - 保留 pre/code → 代码块
    - 保留 a → 链接
    - 保留 img → 图片
    """

    SKIP_TAGS = {
        "script",
        "style",
        "nav",
        "header",
        "footer",
        "aside",
        "noscript",
        "iframe",
        "svg",
        "form",
        "button",
        "input",
        "select",
        "textarea",
        "meta",
        "link",
    }

    def __init__(self):
        super().__init__()
        self.title = ""
        self._parts: list[str] = []
        self._tag_stack: list[str] = []
        self._skip_depth = 0
        self._in_title = False
        self._in_pre = False
        self._current_link: str | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]):
        tag = tag.lower()
        self._tag_stack.append(tag)
        attr_dict = dict(attrs)

        if tag in self.SKIP_TAGS:
            self._skip_depth += 1
            return

        if self._skip_depth > 0:
            return

        if tag == "title":
            self._in_title = True
        elif tag in ("h1", "h2", "h3", "h4", "h5", "h6"):
            level = int(tag[1])
            self._parts.append(f"\n{'#' * level} ")
        elif tag == "p":
            self._parts.append("\n\n")
        elif tag == "br":
            self._parts.append("\n")
        elif tag == "li":
            self._parts.append("\n- ")
        elif tag in ("ul", "ol"):
            self._parts.append("\n")
        elif tag == "pre":
            self._in_pre = True
            self._parts.append("\n```\n")
        elif tag == "code" and not self._in_pre:
            self._parts.append("`")
        elif tag == "a":
            self._current_link = attr_dict.get("href")
            self._parts.append("[")
        elif tag == "img":
            alt = attr_dict.get("alt", "")
            src = attr_dict.get("src", "")
            if src:
                self._parts.append(f"\n![{alt}]({src})\n")
        elif tag == "blockquote":
            self._parts.append("\n> ")
        elif tag in ("strong", "b"):
            self._parts.append("**")
        elif tag in ("em", "i"):
            self._parts.append("*")

    def handle_endtag(self, tag: str):
        tag = tag.lower()
        if self._tag_stack and self._tag_stack[-1] == tag:
            self._tag_stack.pop()

        if tag in self.SKIP_TAGS:
            self._skip_depth = max(0, self._skip_depth - 1)
            return

        if self._skip_depth > 0:
            return

        if tag == "title":
            self._in_title = False
        elif tag in ("h1", "h2", "h3", "h4", "h5", "h6"):
            self._parts.append("\n")
        elif tag == "p":
            self._parts.append("\n")
        elif tag == "pre":
            self._in_pre = False
            self._parts.append("\n```\n")
        elif tag == "code" and not self._in_pre:
            self._parts.append("`")
        elif tag == "a":
            if self._current_link:
                self._parts.append(f"]({self._current_link})")
            else:
                self._parts.append("]")
            self._current_link = None
        elif tag in ("strong", "b"):
            self._parts.append("**")
        elif tag in ("em", "i"):
            self._parts.append("*")

    def handle_data(self, data: str):
        if self._in_title and not self.title:
            self.title = data.strip()

        if self._skip_depth > 0:
            return

        if self._in_pre:
            self._parts.append(data)
        else:
            # 压缩空白
            text = re.sub(r"\s+", " ", data)
            if text.strip():
                self._parts.append(text)

    def get_markdown(self) -> str:
        raw = "".join(self._parts)
        # 清理多余空行
        raw = re.sub(r"\n{3,}", "\n\n", raw)
        return raw.strip()


def extract_page(html: str, url: str) -> WebPage:
    """从 HTML 提取正文并转为 Markdown。"""
    parser = _HTMLTextExtractor()
    parser.feed(html)

    domain = urlparse(url).netloc
    title = parser.title or domain

    return WebPage(
        url=url,
        title=title,
        content=parser.get_markdown(),
        domain=domain,
    )


# ---------------------------------------------------------------------------
# Executor
# ---------------------------------------------------------------------------


class WebClipExecutor:
    """Web Clip Skill 执行层。"""

    def __init__(self):
        self._client: httpx.AsyncClient | None = None

    @property
    def client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(
                timeout=30,
                follow_redirects=True,
                headers={
                    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                },
            )
        return self._client

    async def read(self, url: str) -> str:
        """提取网页正文，返回 Markdown。不保存。"""
        url = _unwrap_url(url)
        page = await self._fetch_and_extract(url)
        return page.to_summary() + "\n\n---\n\n" + page.content

    async def save(
        self, url: str, docs_dir: Path | None = None, category: str = "articles"
    ) -> str:
        """提取网页正文 → LLM 深度整理 → 保存为 wiki 页面。返回页面路径。"""
        url = _unwrap_url(url)
        page = await self._fetch_and_extract(url)

        today = date.today().isoformat()
        safe_title = (
            re.sub(r"[^\w\-]", "-", page.title.lower())[:40].strip("-") or "web-clip"
        )
        display_title = page.title if len(page.title) <= 30 else page.title[:27] + "..."
        filename = f"{safe_title}.md"
        rel_path = f"wiki/{category}/{filename}"

        # LLM 深度整理
        analysis = await self._analyze_content(page)

        content = (
            f"---\n"
            f'title: "{display_title}"\n'
            f"tags: [web-clip, {page.domain}]\n"
            f'source: "{page.url}"\n'
            f"created: {today}\n"
            f"updated: {today}\n"
            f"status: {'developing' if analysis else 'seedling'}\n"
            f"---\n\n"
            f"# {display_title}\n\n"
            f"> 来源: [{page.domain}]({page.url})\n\n"
        )

        if analysis:
            content += analysis + "\n"
        else:
            content += page.content + "\n"

        if docs_dir:
            filepath = docs_dir / rel_path
            filepath.parent.mkdir(parents=True, exist_ok=True)
            filepath.write_text(content, encoding="utf-8")

        return rel_path

    async def _analyze_content(self, page) -> str:
        """用 LLM 深度整理网页内容，生成结构化知识文章。"""
        try:
            from akasha import _get_llm_client

            llm = _get_llm_client()
            if llm is None:
                return ""

            system_prompt = (
                "你是一位专业的知识写作大师，擅长技术文章、概念解析、行业分析等。\n"
                "用户给你一篇网页文章的原文（这是原始素材），"
                "你需要深度理解内容，撰写一篇高质量的知识文章。\n\n"
                "## 写作要求\n"
                "1. 直接输出 Markdown 内容，不要输出 frontmatter\n"
                "2. 用 ## 开头的章节组织内容\n"
                "3. 必须包含以下章节：\n"
                "   - ## 内容概述（1-3 句话总结核心观点）\n"
                "   - ## 核心观点（提炼关键论点，每个展开 2-3 句解释）\n"
                "   - ## 深度解析（按逻辑重新组织，用你的理解重新阐述，"
                "保留关键细节、案例和代码）\n"
                "   - ## 实践启示（读者可以学到什么，如何应用）\n"
                "   - ## 相关概念（涉及的概念/工具/技术/人物/公司，"
                "每个用 [[双链]] 格式）\n"
                "4. 如果有代码或命令，用代码块格式保留\n"
                "5. **不要**原样复制原文，要深度整理和重新表述\n"
                "6. [[双链]] 要覆盖所有关键概念、人物、公司、产品\n"
                "7. [[双链]] 统一使用英文名，如 [[Agent]] 而不是 [[智能体]]，"
                "[[Prompt Engineering]] 而不是 [[提示词工程]]。"
                "如果概念没有通用英文名，再用中文\n"
                "8. 用中文输出"
            )

            user_msg = (
                f"## 文章信息\n"
                f"- 标题: {page.title}\n"
                f"- 来源: {page.url}\n\n"
                f"## 原文内容\n\n{page.content[:30000]}\n\n"
                f"请深度整理为知识文章。"
            )

            return await llm.chat(
                system=system_prompt,
                user=user_msg,
                max_tokens=8192,
                temperature=0.3,
            )
        except Exception as e:
            import sys as _sys

            print(f"[web_clip] LLM 分析失败: {e}", file=_sys.stderr)
            return ""

    async def _fetch_and_extract(self, url: str) -> WebPage:
        """获取 HTML 并提取正文。"""
        resp = await self.client.get(url)
        resp.raise_for_status()
        return extract_page(resp.text, str(resp.url))


def get_executor() -> WebClipExecutor:
    """工厂函数，供 Skill 加载器调用。"""
    return WebClipExecutor()
