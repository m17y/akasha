"""
Media Skill 执行层。

音视频语音转文字:
1. 本地文件 / URL → 下载
2. ffmpeg 提取音频
3. Whisper API 转写（优先 OpenAI API，fallback 本地 whisper CLI）
4. 返回文字稿 / 生成 wiki 页面
"""

from __future__ import annotations

import asyncio
import re
import tempfile
from dataclasses import dataclass
from datetime import date
from pathlib import Path

import httpx


@dataclass
class TranscribeResult:
    """转写结果。"""

    text: str = ""
    source: str = ""
    duration_seconds: float = 0
    language: str = ""

    def to_summary(self) -> str:
        parts = [f"转写完成: {self.source}"]
        if self.duration_seconds:
            m, s = divmod(int(self.duration_seconds), 60)
            parts.append(f"时长: {m}:{s:02d}")
        if self.language:
            parts.append(f"语言: {self.language}")
        parts.append(f"文字: {len(self.text)} 字符")
        return " | ".join(parts)


class MediaExecutor:
    """Media Skill 执行层。"""

    def __init__(self):
        self._client: httpx.AsyncClient | None = None

    @property
    def client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=60, follow_redirects=True)
        return self._client

    async def transcribe(self, source: str) -> str:
        """转写音视频，返回文字稿。

        Args:
            source: 本地文件路径或 URL
        """
        audio_path = await self._prepare_audio(source)
        if not audio_path:
            return f"无法处理: {source}"

        result = await self._whisper(audio_path, source)
        return f"{result.to_summary()}\n\n---\n\n{result.text}"

    async def to_wiki(
        self,
        source: str,
        title: str = "",
        docs_dir: Path | None = None,
    ) -> str:
        """转写音视频 → 生成 wiki 页面。

        Args:
            source: 本地文件路径或 URL
            title: 页面标题（不提供则用文件名）
            docs_dir: docs 目录路径
        """
        audio_path = await self._prepare_audio(source)
        if not audio_path:
            return f"无法处理: {source}"

        result = await self._whisper(audio_path, source)

        if not title:
            title = Path(source).stem if not source.startswith("http") else "语音转写"

        today = date.today().isoformat()
        safe_title = (
            re.sub(r"[^\w\-]", "-", title.lower())[:60].strip("-") or "transcript"
        )
        filename = f"{safe_title}.md"
        rel_path = f"wiki/synthesis/{filename}"

        content = (
            f"---\n"
            f'title: "{title}"\n'
            f"tags: [transcript, media]\n"
            f'source: "{source}"\n'
            f"created: {today}\n"
            f"updated: {today}\n"
            f"status: seedling\n"
            f"---\n\n"
            f"# {title}\n\n"
            f"> 来源: {source}\n\n"
        )
        if result.duration_seconds:
            m, s = divmod(int(result.duration_seconds), 60)
            content += f"- **时长**: {m}:{s:02d}\n"
        if result.language:
            content += f"- **语言**: {result.language}\n"
        content += f"\n## 文字稿\n\n{result.text}\n"

        if docs_dir:
            filepath = docs_dir / rel_path
            filepath.parent.mkdir(parents=True, exist_ok=True)
            filepath.write_text(content, encoding="utf-8")

        return rel_path

    # ── 内部方法 ──

    async def _prepare_audio(self, source: str) -> Path | None:
        """准备音频文件：如果是 URL 先下载，然后用 ffmpeg 提取音频。"""
        tmp_dir = Path(tempfile.gettempdir()) / "akasha_media"
        tmp_dir.mkdir(exist_ok=True)

        # 如果是 URL，先下载
        if source.startswith("http"):
            download_path = tmp_dir / "download_media"
            try:
                async with self.client.stream("GET", source) as resp:
                    resp.raise_for_status()
                    with open(download_path, "wb") as f:
                        async for chunk in resp.aiter_bytes(8192):
                            f.write(chunk)
                source_path = download_path
            except Exception:
                return None
        else:
            source_path = Path(source)
            if not source_path.exists():
                return None

        # 用 ffmpeg 转成 wav（whisper 需要）
        audio_path = tmp_dir / "audio.wav"
        try:
            proc = await asyncio.create_subprocess_exec(
                "ffmpeg",
                "-y",
                "-i",
                str(source_path),
                "-ar",
                "16000",  # 16kHz
                "-ac",
                "1",  # mono
                "-f",
                "wav",
                str(audio_path),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            await asyncio.wait_for(proc.communicate(), timeout=120)
            if proc.returncode != 0 or not audio_path.exists():
                return None
        except (FileNotFoundError, asyncio.TimeoutError):
            # ffmpeg 不可用，直接用源文件（whisper 也能处理部分格式）
            audio_path = source_path

        return audio_path

    async def _whisper(self, audio_path: Path, source: str) -> TranscribeResult:
        """调用 whisper 转写。优先 whisper CLI，fallback 到 OpenAI API。"""
        # 尝试本地 whisper CLI
        result = await self._whisper_cli(audio_path, source)
        if result:
            return result

        # fallback: OpenAI Whisper API
        result = await self._whisper_api(audio_path, source)
        if result:
            return result

        return TranscribeResult(
            text="(转写失败: whisper CLI 和 API 均不可用)", source=source
        )

    async def _whisper_cli(
        self, audio_path: Path, source: str
    ) -> TranscribeResult | None:
        """本地 whisper CLI 转写。"""
        try:
            output_dir = audio_path.parent
            proc = await asyncio.create_subprocess_exec(
                "whisper",
                str(audio_path),
                "--model",
                "base",
                "--language",
                "zh",
                "--output_format",
                "txt",
                "--output_dir",
                str(output_dir),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            await asyncio.wait_for(proc.communicate(), timeout=300)

            if proc.returncode != 0:
                return None

            # whisper 输出 audio.txt
            txt_path = output_dir / f"{audio_path.stem}.txt"
            if txt_path.exists():
                text = txt_path.read_text(encoding="utf-8").strip()
                return TranscribeResult(text=text, source=source, language="zh")
            return None
        except (FileNotFoundError, asyncio.TimeoutError):
            return None

    async def _whisper_api(
        self, audio_path: Path, source: str
    ) -> TranscribeResult | None:
        """OpenAI Whisper API 转写。需要 AKASHA_LLM_API_KEY。"""
        import os

        api_key = os.getenv("AKASHA_LLM_API_KEY", "")
        base_url = os.getenv("AKASHA_LLM_BASE_URL", "https://api.openai.com/v1")
        if not api_key:
            return None

        try:
            url = f"{base_url.rstrip('/')}/audio/transcriptions"
            with open(audio_path, "rb") as f:
                resp = await self.client.post(
                    url,
                    headers={"Authorization": f"Bearer {api_key}"},
                    files={"file": (audio_path.name, f, "audio/wav")},
                    data={"model": "whisper-1", "language": "zh"},
                    timeout=120,
                )
            resp.raise_for_status()
            data = resp.json()
            text = data.get("text", "")
            return (
                TranscribeResult(text=text, source=source, language="zh")
                if text
                else None
            )
        except Exception:
            return None


def get_executor() -> MediaExecutor:
    """工厂函数。"""
    return MediaExecutor()
