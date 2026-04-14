"""
Tests for media skill.
"""

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from akasha.skills.media.executor import MediaExecutor, TranscribeResult, get_executor
from akasha.skills import discover_skills


# ============================================================================
# discover
# ============================================================================


class TestDiscoverMedia:
    def test_discover(self):
        skills_dir = Path(__file__).parent.parent / "akasha" / "skills"
        skills = discover_skills(skills_dir)
        names = [s.name for s in skills]
        assert "media" in names

    def test_fields(self):
        skills_dir = Path(__file__).parent.parent / "akasha" / "skills"
        skills = discover_skills(skills_dir)
        media = next(s for s in skills if s.name == "media")
        assert "media_transcribe" in media.tools
        assert "media_to_wiki" in media.tools


# ============================================================================
# TranscribeResult
# ============================================================================


class TestTranscribeResult:
    def test_summary(self):
        r = TranscribeResult(
            text="Hello world",
            source="/tmp/test.mp4",
            duration_seconds=125,
            language="zh",
        )
        s = r.to_summary()
        assert "test.mp4" in s
        assert "2:05" in s
        assert "zh" in s

    def test_summary_no_duration(self):
        r = TranscribeResult(text="Hi", source="test.wav")
        s = r.to_summary()
        assert "test.wav" in s


# ============================================================================
# MediaExecutor
# ============================================================================


class TestMediaExecutor:
    @pytest.mark.asyncio
    async def test_transcribe_with_mock(self):
        """Mock whisper CLI 成功。"""
        ex = MediaExecutor()

        mock_result = TranscribeResult(
            text="这是测试转写的文字内容",
            source="/tmp/test.mp4",
            duration_seconds=60,
            language="zh",
        )

        with patch.object(ex, "_prepare_audio", return_value=Path("/tmp/audio.wav")):
            with patch.object(ex, "_whisper", return_value=mock_result):
                result = await ex.transcribe("/tmp/test.mp4")

        assert "测试转写" in result
        assert "60" in result or "1:00" in result

    @pytest.mark.asyncio
    async def test_transcribe_source_not_found(self):
        """不存在的文件应返回提示。"""
        ex = MediaExecutor()
        result = await ex.transcribe("/nonexistent/file.mp4")
        assert "无法处理" in result

    @pytest.mark.asyncio
    async def test_to_wiki_generates_file(self, tmp_path: Path):
        """to_wiki 应生成 wiki 页面。"""
        ex = MediaExecutor()
        docs_dir = tmp_path / "docs"
        (docs_dir / "wiki" / "synthesis").mkdir(parents=True)

        mock_result = TranscribeResult(
            text="这是一段很长的转写文字，包含了视频里的所有语音内容。",
            source="https://example.com/video.mp4",
            duration_seconds=300,
            language="zh",
        )

        with patch.object(ex, "_prepare_audio", return_value=Path("/tmp/audio.wav")):
            with patch.object(ex, "_whisper", return_value=mock_result):
                path = await ex.to_wiki(
                    "https://example.com/video.mp4",
                    title="测试视频转写",
                    docs_dir=docs_dir,
                )

        assert path.startswith("wiki/synthesis/")
        assert (docs_dir / path).exists()

        content = (docs_dir / path).read_text(encoding="utf-8")
        assert "测试视频转写" in content
        assert "转写文字" in content
        assert "transcript" in content
        assert "5:00" in content

    @pytest.mark.asyncio
    async def test_to_wiki_no_docs_dir(self):
        """不提供 docs_dir 应返回路径但不写文件。"""
        ex = MediaExecutor()

        mock_result = TranscribeResult(text="Hello", source="test.mp4")

        with patch.object(ex, "_prepare_audio", return_value=Path("/tmp/audio.wav")):
            with patch.object(ex, "_whisper", return_value=mock_result):
                path = await ex.to_wiki("test.mp4", title="Test")

        assert path.startswith("wiki/synthesis/")

    def test_get_executor(self):
        ex = get_executor()
        assert isinstance(ex, MediaExecutor)
