"""
Tests for akasha.skills — Skill 发现、加载、video executor。
"""

import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from akasha.skills import (
    SkillDef,
    discover_skills,
    load_executor,
    _parse_skill_frontmatter,
)
from akasha.skills.video.executor import VideoExecutor, VideoInfo, get_executor


# ============================================================================
# _parse_skill_frontmatter
# ============================================================================


class TestParseSkillFrontmatter:
    def test_valid_frontmatter(self):
        text = "---\nname: video\ndescription: test\ntools:\n  - a\n  - b\n---\n# Body"
        meta = _parse_skill_frontmatter(text)
        assert meta["name"] == "video"
        assert meta["tools"] == ["a", "b"]

    def test_no_frontmatter(self):
        meta = _parse_skill_frontmatter("# No frontmatter")
        assert meta == {}

    def test_invalid_yaml(self):
        meta = _parse_skill_frontmatter("---\n: bad: {{{\n---\nbody")
        assert meta == {}


# ============================================================================
# discover_skills
# ============================================================================


class TestDiscoverSkills:
    def test_discover_video_skill(self):
        """应能发现内置的 video skill。"""
        skills_dir = Path(__file__).parent.parent / "akasha" / "skills"
        skills = discover_skills(skills_dir)
        names = [s.name for s in skills]
        assert "video" in names

    def test_video_skill_fields(self):
        skills_dir = Path(__file__).parent.parent / "akasha" / "skills"
        skills = discover_skills(skills_dir)
        video = next(s for s in skills if s.name == "video")
        assert video.description
        assert "video_download" in video.tools
        assert "video_info" in video.tools
        assert "video_to_wiki" in video.tools
        assert video.skill_dir.name == "video"
        assert "Video Skill" in video.prompt

    def test_empty_dir(self, tmp_path: Path):
        skills = discover_skills(tmp_path)
        assert skills == []

    def test_nonexistent_dir(self, tmp_path: Path):
        skills = discover_skills(tmp_path / "nonexistent")
        assert skills == []

    def test_dir_without_skill_md(self, tmp_path: Path):
        (tmp_path / "fake_skill").mkdir()
        (tmp_path / "fake_skill" / "executor.py").write_text("pass", encoding="utf-8")
        skills = discover_skills(tmp_path)
        assert skills == []

    def test_skips_underscore_dirs(self, tmp_path: Path):
        pycache = tmp_path / "__pycache__"
        pycache.mkdir()
        (pycache / "skill.md").write_text("---\nname: bad\n---\n", encoding="utf-8")
        skills = discover_skills(tmp_path)
        assert skills == []

    def test_custom_skill(self, tmp_path: Path):
        """自定义 skill 目录应被发现。"""
        skill_dir = tmp_path / "my_skill"
        skill_dir.mkdir()
        (skill_dir / "skill.md").write_text(
            "---\nname: my_skill\ndescription: test skill\ntools:\n  - my_tool\n---\n# My Skill\n",
            encoding="utf-8",
        )
        skills = discover_skills(tmp_path)
        assert len(skills) == 1
        assert skills[0].name == "my_skill"
        assert skills[0].tools == ["my_tool"]


# ============================================================================
# load_executor
# ============================================================================


class TestLoadExecutor:
    def test_load_video_executor(self):
        skills_dir = Path(__file__).parent.parent / "akasha" / "skills"
        skills = discover_skills(skills_dir)
        video = next(s for s in skills if s.name == "video")
        executor = load_executor(video)
        assert isinstance(executor, VideoExecutor)


# ============================================================================
# VideoInfo
# ============================================================================


class TestVideoInfo:
    def test_duration_str(self):
        info = VideoInfo(duration=125)
        assert info.duration_str() == "2:05"

    def test_duration_str_hours(self):
        info = VideoInfo(duration=3661)
        assert info.duration_str() == "1:01:01"

    def test_to_dict(self):
        info = VideoInfo(title="Test", author="A", platform="youtube")
        d = info.to_dict()
        assert d["title"] == "Test"
        assert d["platform"] == "youtube"

    def test_to_summary(self):
        info = VideoInfo(
            title="Test Video",
            author="Author",
            platform="bilibili",
            duration=120,
            view_count=1000,
        )
        summary = info.to_summary()
        assert "Test Video" in summary
        assert "Author" in summary
        assert "bilibili" in summary
        assert "2:00" in summary


# ============================================================================
# VideoExecutor
# ============================================================================


class TestVideoExecutor:
    def test_detect_platform(self):
        ex = VideoExecutor()
        assert ex._detect_platform("https://www.douyin.com/video/123") == "douyin"
        assert ex._detect_platform("https://www.bilibili.com/video/BV1xx") == "bilibili"
        assert ex._detect_platform("https://b23.tv/abc") == "bilibili"
        assert ex._detect_platform("https://www.youtube.com/watch?v=abc") == "youtube"
        assert ex._detect_platform("https://youtu.be/abc") == "youtube"
        assert ex._detect_platform("https://www.tiktok.com/@user/video/123") == "tiktok"
        assert ex._detect_platform("https://example.com/video") == "unknown"

    @pytest.mark.asyncio
    async def test_info_with_mock_tikwm(self):
        """Mock tikwm API 返回。"""
        ex = VideoExecutor()
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "code": 0,
            "data": {
                "title": "测试视频",
                "author": {"nickname": "测试作者"},
                "duration": 30,
                "hdplay": "https://example.com/video.mp4",
                "play_count": 5000,
                "create_time": "1700000000",
            },
        }
        mock_response.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_response)
        ex._client = mock_client

        info = await ex.info("https://www.douyin.com/video/123")

        assert info.title == "测试视频"
        assert info.author == "测试作者"
        assert info.platform == "douyin"
        assert info.duration == 30
        assert info.download_url == "https://example.com/video.mp4"

    @pytest.mark.asyncio
    async def test_info_tikwm_fails_fallback_ytdlp(self):
        """tikwm 失败时应 fallback 到 yt-dlp。"""
        ex = VideoExecutor()

        # tikwm 返回错误
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"code": -1}
        mock_resp.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_resp)
        ex._client = mock_client

        # yt-dlp mock
        ytdlp_data = json.dumps(
            {
                "title": "ytdlp video",
                "uploader": "ytdlp author",
                "duration": 60,
                "webpage_url": "https://www.douyin.com/video/123",
                "upload_date": "20260414",
            }
        ).encode()

        with patch("asyncio.create_subprocess_exec") as mock_proc:
            proc = AsyncMock()
            proc.returncode = 0
            proc.communicate = AsyncMock(return_value=(ytdlp_data, b""))
            mock_proc.return_value = proc

            info = await ex.info("https://www.douyin.com/video/123")

        assert info.title == "ytdlp video"
        assert info.author == "ytdlp author"

    @pytest.mark.asyncio
    async def test_to_wiki_with_video_embed(self, tmp_path: Path):
        """to_wiki 应下载视频并在 wiki 中嵌入 <video> 标签。"""
        ex = VideoExecutor()
        docs_dir = tmp_path / "docs"
        (docs_dir / "wiki" / "entities").mkdir(parents=True)
        (docs_dir / "assets" / "video").mkdir(parents=True)

        mock_info = VideoInfo(
            title="Test Wiki Video",
            author="Wiki Author",
            platform="youtube",
            duration=180,
            description="A test video for wiki generation.",
            url="https://youtube.com/watch?v=test",
            download_url="https://example.com/video.mp4",
            tags=["test", "video"],
        )

        # Mock info + 下载流 (httpx stream 返回同步 context manager)
        class FakeResp:
            def raise_for_status(self):
                pass

            async def aiter_bytes(self, n):
                yield b"\x00" * 1024

            async def __aenter__(self):
                return self

            async def __aexit__(self, *a):
                pass

        mock_client = AsyncMock()
        mock_client.stream = MagicMock(return_value=FakeResp())
        mock_client.get = AsyncMock(return_value=MagicMock())
        ex._client = mock_client

        with patch.object(ex, "info", return_value=mock_info):
            path = await ex.to_wiki(
                "https://youtube.com/watch?v=test", docs_dir=docs_dir
            )

        assert path.startswith("wiki/entities/")
        assert (docs_dir / path).exists()

        content = (docs_dir / path).read_text(encoding="utf-8")
        # 验证视频嵌入
        assert "<video" in content
        assert "assets/video/" in content
        assert ".mp4" in content
        # 验证源链接保留
        assert "youtube.com" in content
        # 验证元信息
        assert "Test Wiki Video" in content
        assert "Wiki Author" in content

        # 验证视频文件已下载
        video_files = list((docs_dir / "assets" / "video").glob("*.mp4"))
        assert len(video_files) == 1

    @pytest.mark.asyncio
    async def test_to_wiki_download_fails_uses_link(self, tmp_path: Path):
        """视频下载失败时应 fallback 到嵌入源链接。"""
        ex = VideoExecutor()
        docs_dir = tmp_path / "docs"
        (docs_dir / "wiki" / "entities").mkdir(parents=True)

        mock_info = VideoInfo(
            title="Fallback Video",
            platform="bilibili",
            url="https://bilibili.com/video/BV1xx",
            download_url="https://bad-url.example.com/fail.mp4",
        )

        # Mock: 下载会失败
        class FailResp:
            def raise_for_status(self):
                raise httpx.HTTPError("connection failed")

            async def aiter_bytes(self, n):
                yield b""

            async def __aenter__(self):
                return self

            async def __aexit__(self, *a):
                pass

        mock_client = AsyncMock()
        mock_client.stream = MagicMock(return_value=FailResp())
        ex._client = mock_client

        with patch.object(ex, "info", return_value=mock_info):
            path = await ex.to_wiki(
                "https://bilibili.com/video/BV1xx", docs_dir=docs_dir
            )

        content = (docs_dir / path).read_text(encoding="utf-8")
        # 下载失败，应 fallback 嵌入远程链接
        assert "<video" in content
        assert "bad-url.example.com/fail.mp4" in content

    @pytest.mark.asyncio
    async def test_to_wiki_no_download_url(self, tmp_path: Path):
        """没有 download_url 时不嵌入视频，只保留源链接。"""
        ex = VideoExecutor()
        docs_dir = tmp_path / "docs"
        (docs_dir / "wiki" / "entities").mkdir(parents=True)

        mock_info = VideoInfo(
            title="No Download",
            platform="unknown",
            url="https://example.com/page",
        )

        with patch.object(ex, "info", return_value=mock_info):
            path = await ex.to_wiki("https://example.com/page", docs_dir=docs_dir)

        content = (docs_dir / path).read_text(encoding="utf-8")
        assert "example.com/page" in content
        # 没有 download_url 就不应有 <video> 标签
        assert "<video" not in content

    @pytest.mark.asyncio
    async def test_to_wiki_no_docs_dir(self):
        """不提供 docs_dir 时应仍返回路径（但不写文件不下载）。"""
        ex = VideoExecutor()
        mock_info = VideoInfo(title="No Write", platform="bilibili")

        with patch.object(ex, "info", return_value=mock_info):
            path = await ex.to_wiki("https://bilibili.com/video/BV1xx")

        assert path.startswith("wiki/entities/")
