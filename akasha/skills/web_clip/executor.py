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
from urllib.parse import urlparse

import httpx


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
        page = await self._fetch_and_extract(url)
        return page.to_summary() + "\n\n---\n\n" + page.content

    async def save(
        self, url: str, docs_dir: Path | None = None, category: str = "articles"
    ) -> str:
        """提取网页正文并保存为 wiki 页面。返回页面路径。"""
        page = await self._fetch_and_extract(url)

        today = date.today().isoformat()
        safe_title = (
            re.sub(r"[^\w\-]", "-", page.title.lower())[:60].strip("-") or "web-clip"
        )
        filename = f"{safe_title}.md"
        rel_path = f"wiki/{category}/{filename}"

        content = (
            f"---\n"
            f'title: "{page.title}"\n'
            f"tags: [web-clip, {page.domain}]\n"
            f'source: "{page.url}"\n'
            f"created: {today}\n"
            f"updated: {today}\n"
            f"status: seedling\n"
            f"---\n\n"
            f"# {page.title}\n\n"
            f"> 来源: [{page.url}]({page.url})\n\n"
            f"{page.content}\n"
        )

        if docs_dir:
            filepath = docs_dir / rel_path
            filepath.parent.mkdir(parents=True, exist_ok=True)
            filepath.write_text(content, encoding="utf-8")

        return rel_path

    async def _fetch_and_extract(self, url: str) -> WebPage:
        """获取 HTML 并提取正文。"""
        resp = await self.client.get(url)
        resp.raise_for_status()
        return extract_page(resp.text, str(resp.url))


def get_executor() -> WebClipExecutor:
    """工厂函数，供 Skill 加载器调用。"""
    return WebClipExecutor()
