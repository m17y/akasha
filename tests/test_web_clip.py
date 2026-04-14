"""
Tests for web_clip skill.
"""

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from akasha.skills.web_clip.executor import (
    WebClipExecutor,
    WebPage,
    extract_page,
    get_executor,
)
from akasha.skills import discover_skills


# ============================================================================
# discover
# ============================================================================


class TestDiscoverWebClip:
    def test_discover(self):
        skills_dir = Path(__file__).parent.parent / "akasha" / "skills"
        skills = discover_skills(skills_dir)
        names = [s.name for s in skills]
        assert "web_clip" in names

    def test_fields(self):
        skills_dir = Path(__file__).parent.parent / "akasha" / "skills"
        skills = discover_skills(skills_dir)
        wc = next(s for s in skills if s.name == "web_clip")
        assert "web_clip_save" in wc.tools
        assert "web_clip_read" in wc.tools


# ============================================================================
# extract_page
# ============================================================================


class TestExtractPage:
    def test_basic_html(self):
        html = """
        <html>
        <head><title>Test Page</title></head>
        <body>
        <nav>skip this</nav>
        <h1>Hello World</h1>
        <p>This is a paragraph with <strong>bold</strong> and <em>italic</em>.</p>
        <ul><li>Item 1</li><li>Item 2</li></ul>
        <footer>skip footer</footer>
        </body>
        </html>
        """
        page = extract_page(html, "https://example.com/test")
        assert page.title == "Test Page"
        assert page.domain == "example.com"
        assert "# Hello World" in page.content
        assert "**bold**" in page.content
        assert "*italic*" in page.content
        assert "- Item 1" in page.content
        # nav 和 footer 应被跳过
        assert "skip this" not in page.content
        assert "skip footer" not in page.content

    def test_code_block(self):
        html = "<html><body><pre>def hello():\n    print('hi')</pre></body></html>"
        page = extract_page(html, "https://example.com")
        assert "```" in page.content
        assert "def hello():" in page.content

    def test_links(self):
        html = '<html><body><p>Visit <a href="https://example.com">Example</a>.</p></body></html>'
        page = extract_page(html, "https://example.com")
        assert "[Example](https://example.com)" in page.content

    def test_images(self):
        html = '<html><body><img src="pic.jpg" alt="A picture"></body></html>'
        page = extract_page(html, "https://example.com")
        assert "![A picture](pic.jpg)" in page.content

    def test_script_style_removed(self):
        html = """
        <html><body>
        <script>var x = 1;</script>
        <style>.foo { color: red; }</style>
        <p>Real content</p>
        </body></html>
        """
        page = extract_page(html, "https://example.com")
        assert "var x" not in page.content
        assert "color: red" not in page.content
        assert "Real content" in page.content

    def test_empty_html(self):
        page = extract_page("", "https://example.com")
        assert page.title == "example.com"
        assert page.content == ""

    def test_headings_levels(self):
        html = "<html><body><h1>H1</h1><h2>H2</h2><h3>H3</h3></body></html>"
        page = extract_page(html, "https://example.com")
        assert "# H1" in page.content
        assert "## H2" in page.content
        assert "### H3" in page.content


# ============================================================================
# WebPage
# ============================================================================


class TestWebPage:
    def test_to_summary(self):
        page = WebPage(
            url="https://example.com/article",
            title="Test Article",
            content="Hello world content here.",
            domain="example.com",
        )
        summary = page.to_summary()
        assert "Test Article" in summary
        assert "example.com" in summary
        assert "25 字符" in summary


# ============================================================================
# WebClipExecutor
# ============================================================================


class TestWebClipExecutor:
    @pytest.mark.asyncio
    async def test_read(self):
        ex = WebClipExecutor()
        mock_resp = MagicMock()
        mock_resp.text = "<html><head><title>Mock</title></head><body><p>Hello from mock</p></body></html>"
        mock_resp.url = "https://example.com/mock"
        mock_resp.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_resp)
        ex._client = mock_client

        result = await ex.read("https://example.com/mock")
        assert "Mock" in result
        assert "Hello from mock" in result

    @pytest.mark.asyncio
    async def test_save(self, tmp_path: Path):
        ex = WebClipExecutor()
        docs_dir = tmp_path / "docs"
        (docs_dir / "wiki" / "articles").mkdir(parents=True)

        mock_resp = MagicMock()
        mock_resp.text = """
        <html><head><title>Great Article</title></head>
        <body><h1>Great Article</h1><p>This is important content worth saving.</p></body>
        </html>
        """
        mock_resp.url = "https://blog.example.com/great-article"
        mock_resp.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_resp)
        ex._client = mock_client

        path = await ex.save(
            "https://blog.example.com/great-article", docs_dir=docs_dir
        )

        assert path.startswith("wiki/articles/")
        assert (docs_dir / path).exists()

        content = (docs_dir / path).read_text(encoding="utf-8")
        assert "Great Article" in content
        assert "blog.example.com" in content
        assert "web-clip" in content
        assert "important content" in content

    @pytest.mark.asyncio
    async def test_save_no_docs_dir(self):
        ex = WebClipExecutor()
        mock_resp = MagicMock()
        mock_resp.text = "<html><head><title>No Save</title></head><body><p>Content</p></body></html>"
        mock_resp.url = "https://example.com"
        mock_resp.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_resp)
        ex._client = mock_client

        path = await ex.save("https://example.com")
        assert path.startswith("wiki/articles/")

    def test_get_executor(self):
        ex = get_executor()
        assert isinstance(ex, WebClipExecutor)
