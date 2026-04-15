"""
Video Skill 执行层。

逻辑在 skill.md 里定义，这里只管调工具:
- tikwm API: 抖音/TikTok 无水印下载
- yt-dlp: 万能后端 (B站/YouTube/通用)
"""

from __future__ import annotations

import asyncio
import json
import re
import sys
import tempfile
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from urllib.parse import unquote, urlparse, parse_qs

import httpx


# ---------------------------------------------------------------------------
# URL 解包 — 从飞书/微信/知乎等安全跳转链接中提取真实 URL
# ---------------------------------------------------------------------------

_REDIRECT_HOSTS = {
    "security.feishu.cn",
    "link.zhihu.com",
    "weixin110.qq.com",
}


def _unwrap_url(url: str) -> str:
    """从包装链接中提取真实 URL。"""
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


@dataclass
class VideoInfo:
    """视频元信息。"""

    title: str = ""
    author: str = ""
    platform: str = ""
    duration: int = 0  # 秒
    description: str = ""
    url: str = ""
    download_url: str = ""
    publish_date: str = ""
    view_count: int = 0
    tags: list[str] = field(default_factory=list)
    extra: dict = field(default_factory=dict)

    def duration_str(self) -> str:
        m, s = divmod(self.duration, 60)
        h, m = divmod(m, 60)
        if h:
            return f"{h}:{m:02d}:{s:02d}"
        return f"{m}:{s:02d}"

    def to_dict(self) -> dict:
        return {
            "title": self.title,
            "author": self.author,
            "platform": self.platform,
            "duration": self.duration_str(),
            "description": self.description,
            "url": self.url,
            "download_url": self.download_url,
            "publish_date": self.publish_date,
            "view_count": self.view_count,
            "tags": self.tags,
        }

    def to_summary(self) -> str:
        parts = [f"**{self.title}**\n"]
        parts.append(f"- 作者: {self.author}")
        parts.append(f"- 平台: {self.platform}")
        if self.duration:
            parts.append(f"- 时长: {self.duration_str()}")
        if self.publish_date:
            parts.append(f"- 发布: {self.publish_date}")
        if self.view_count:
            parts.append(f"- 播放: {self.view_count:,}")
        if self.description:
            desc = self.description[:200]
            if len(self.description) > 200:
                desc += "..."
            parts.append(f"- 简介: {desc}")
        if self.tags:
            parts.append(f"- 标签: {', '.join(self.tags[:10])}")
        if self.download_url:
            parts.append(f"- 下载链接: {self.download_url}")
        return "\n".join(parts)


class VideoExecutor:
    """视频 Skill 执行层。"""

    def __init__(self):
        self._client: httpx.AsyncClient | None = None

    @property
    def client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=30, follow_redirects=True)
        return self._client

    # ── 公开方法 (对应 MCP tools) ──

    async def download(self, url: str, docs_dir: Path | None = None) -> str:
        """下载视频。如果提供 docs_dir 则下载到 docs/assets/video/，否则临时目录。"""
        url = _unwrap_url(url)
        info = await self.info(url)
        if not info.download_url:
            return f"无法获取下载链接: {url}"

        safe_title = re.sub(r"[^\w\-.]", "_", info.title or "video")[:50]
        video_filename = f"{safe_title}.mp4"

        if docs_dir:
            download_dir = docs_dir / "assets" / "video"
        else:
            download_dir = Path(tempfile.gettempdir()) / "akasha_video"
        download_dir.mkdir(parents=True, exist_ok=True)

        filepath = download_dir / video_filename

        try:
            async with self.client.stream("GET", info.download_url) as resp:
                resp.raise_for_status()
                with open(filepath, "wb") as f:
                    async for chunk in resp.aiter_bytes(8192):
                        f.write(chunk)
        except Exception as e:
            return f"下载失败: {e}"

        size_mb = filepath.stat().st_size / 1024 / 1024
        return f"下载完成: {filepath}\n大小: {size_mb:.1f} MB\n\n{info.to_summary()}"

    async def info(self, url: str) -> VideoInfo:
        """获取视频信息（不下载）。"""
        url = _unwrap_url(url)
        platform = self._detect_platform(url)

        # 级联尝试
        if platform in ("douyin", "tiktok"):
            # 1. tikwm API（需要短链接格式）
            result = await self._tikwm(url, platform)
            if result:
                return result
            # 2. 抖音 web 分享页解析
            result = await self._douyin_web(url)
            if result:
                return result

        # 3. yt-dlp 万能后端
        result = await self._ytdlp(url, platform)
        if result:
            return result

        return VideoInfo(url=url, platform=platform, title="(无法解析)")

    async def to_wiki(self, url: str, docs_dir: Path | None = None) -> str:
        """解析视频 → 下载 → 转写语音 → LLM 分析 → 生成知识文档。返回页面路径。"""
        url = _unwrap_url(url)
        info = await self.info(url)

        if info.title == "(无法解析)":
            return f"无法解析视频信息: {url}"

        # 文件名：最长 40 字符
        safe_title = (
            re.sub(r"[^\w\-]", "-", info.title.lower())[:40].strip("-") or "video"
        )
        # 页面标题：最长 30 字符
        display_title = info.title if len(info.title) <= 30 else info.title[:27] + "..."
        video_filename = f"{safe_title}.mp4"
        wiki_filename = f"{safe_title}.md"
        rel_path = f"wiki/articles/{wiki_filename}"

        # 检查是否已存在同名页面（避免重复生成）
        if docs_dir:
            existing = docs_dir / rel_path
            if existing.exists():
                return f"已存在: {rel_path}（跳过重复生成）"

        # Step 1: 下载视频
        video_downloaded = False
        video_path: Path | None = None
        if docs_dir and info.download_url:
            video_dir = docs_dir / "assets" / "video"
            video_dir.mkdir(parents=True, exist_ok=True)
            video_path = video_dir / video_filename

            try:
                async with self.client.stream("GET", info.download_url) as resp:
                    resp.raise_for_status()
                    with open(video_path, "wb") as f:
                        async for chunk in resp.aiter_bytes(8192):
                            f.write(chunk)
                video_downloaded = True
            except Exception:
                video_path = None

        # Step 2: 转写语音（从下载的视频提取音频 → whisper）
        transcript = ""
        if video_downloaded and video_path:
            transcript = await self._transcribe_video(video_path)
            # 转写失败的内容不算有效转写
            if "转写失败" in transcript:
                transcript = ""

        # Step 3: LLM 分析内容，生成结构化知识文档 + 创建概念/实体页面
        llm_analysis = ""
        if transcript:
            llm_analysis = await self._analyze_content(info, transcript)

        # Step 4: 生成 wiki 页面
        today = date.today().isoformat()
        content = (
            f"---\n"
            f'title: "{display_title}"\n'
            f"tags: [video, {info.platform}]\n"
            f'source: "{info.url}"\n'
            f"created: {today}\n"
            f"updated: {today}\n"
            f"status: {'developing' if llm_analysis else 'seedling'}\n"
            f"---\n\n"
            f"# {display_title}\n\n"
        )

        # 嵌入视频（用站点根路径，兼容 mkdocs 构建后的 URL 结构）
        if video_downloaded:
            from urllib.parse import quote

            encoded_filename = quote(video_filename)
            content += (
                f'<video controls width="100%">\n'
                f'  <source src="/assets/video/{encoded_filename}" type="video/mp4">\n'
                f"  你的浏览器不支持视频播放。\n"
                f"</video>\n\n"
            )
        elif info.download_url:
            content += (
                f'<video controls width="100%">\n'
                f'  <source src="{info.download_url}" type="video/mp4">\n'
                f"  你的浏览器不支持视频播放。\n"
                f"</video>\n\n"
            )

        content += f"> 源链接: [{info.url}]({info.url})\n\n"

        # 元信息
        content += f"- **作者**: {info.author}\n- **平台**: {info.platform}\n"
        if info.duration:
            content += f"- **时长**: {info.duration_str()}\n"
        if info.publish_date:
            content += f"- **发布日期**: {info.publish_date}\n"
        if info.view_count:
            content += f"- **播放量**: {info.view_count:,}\n"
        content += "\n"

        # LLM 分析结果（核心内容）
        if llm_analysis:
            content += llm_analysis + "\n"
        else:
            # fallback: LLM 分析失败时用视频描述
            content += f"## 摘要\n\n{info.description or '(暂无内容，LLM 分析失败)'}\n"

        if info.tags:
            tags_str = ", ".join(info.tags[:10])
            content += f"\n## 标签\n\n{tags_str}\n"

        # 写入文件
        if docs_dir:
            filepath = docs_dir / rel_path
            filepath.parent.mkdir(parents=True, exist_ok=True)
            filepath.write_text(content, encoding="utf-8")

        return rel_path

    async def _transcribe_video(self, video_path: Path) -> str:
        """从视频中提取音频并转写为文字。"""
        try:
            from ..media.executor import MediaExecutor

            media = MediaExecutor()
            result = await media.transcribe(str(video_path))
            # transcribe 返回格式: "转写完成: ... | ...\n\n---\n\n实际文字"
            if "---" in result:
                return result.split("---", 1)[1].strip()
            return result
        except Exception as e:
            print(f"[video] 转写失败: {e}", file=sys.stderr)
            return ""

    async def _analyze_content(self, info: VideoInfo, transcript: str) -> str:
        """用 LLM 分析转写内容，生成结构化知识文档。"""
        try:
            from akasha import _get_llm_client

            llm = _get_llm_client()
            if llm is None:
                return ""

            system_prompt = (
                "你是一位专业的知识写作大师，擅长技术文章、概念解析、行业分析等。\n"
                "用户给你一段视频的转写文字稿（这是原始素材，不要直接展示），"
                "你需要基于文字稿深度理解内容，撰写一篇高质量的知识文章。\n\n"
                "## 写作要求\n"
                "1. 直接输出 Markdown 内容，不要输出 frontmatter\n"
                "2. 用 ## 开头的章节组织内容\n"
                "3. 必须包含以下章节：\n"
                "   - ## 内容概述（1-3 句话总结核心观点，有深度）\n"
                "   - ## 核心观点（提炼作者的关键论点，每个论点展开 2-3 句解释）\n"
                "   - ## 深度解析（按逻辑重新组织内容，不是简单摘抄，"
                "而是用你的理解重新阐述，保留关键细节、案例和步骤）\n"
                "   - ## 实践启示（读者可以从中学到什么，如何应用）\n"
                "   - ## 相关概念（列出涉及的重要概念/工具/技术/人物/公司，"
                "每个用 [[双链]] 格式，如 [[Agent]]、[[LangChain]]）\n"
                "4. 如果是教程类内容，深度解析中要保留完整操作步骤\n"
                "5. 如果有代码或命令，用代码块格式保留\n"
                "6. **不要**包含原始文字稿，文字稿仅供你理解内容用\n"
                "7. 内容要详尽、有深度，体现你的专业理解\n"
                "8. [[双链]] 要覆盖所有提到的关键概念、人物、公司、产品、框架\n"
                "9. 用中文输出"
            )

            user_msg = (
                f"## 视频信息\n"
                f"- 标题: {info.title}\n"
                f"- 作者: {info.author}\n"
                f"- 平台: {info.platform}\n"
                f"- 时长: {info.duration_str()}\n\n"
                f"## 转写文字稿\n\n{transcript[:30000]}\n\n"
                f"请整理为结构化的知识文档。"
            )

            result = await llm.chat(
                system=system_prompt,
                user=user_msg,
                max_tokens=8192,
                temperature=0.3,
            )

            return result
        except Exception as e:
            print(f"[video] LLM 分析失败: {e}", file=sys.stderr)
            return ""

    # ── 后端实现 ──

    async def _tikwm(self, url: str, platform: str) -> VideoInfo | None:
        """tikwm API — 抖音/TikTok 无水印。"""
        try:
            resp = await self.client.get(
                "https://www.tikwm.com/api/",
                params={"url": url, "hd": 1},
            )
            resp.raise_for_status()
            data = resp.json()

            if data.get("code") != 0 or not data.get("data"):
                return None

            d = data["data"]
            return VideoInfo(
                title=d.get("title", ""),
                author=d.get("author", {}).get("nickname", ""),
                platform=platform,
                duration=d.get("duration", 0),
                description=d.get("title", ""),
                url=url,
                download_url=d.get("hdplay") or d.get("play", ""),
                publish_date=str(d.get("create_time", "")),
                view_count=d.get("play_count", 0),
                tags=[],
            )
        except Exception:
            return None

    async def _douyin_web(self, url: str) -> VideoInfo | None:
        """抖音 web 分享页解析 — 从 iesdouyin.com SSR 页面提取数据。"""
        try:
            # 从 URL 提取视频 ID
            m = re.search(r"/video/(\d+)", url)
            if not m:
                return None
            video_id = m.group(1)

            share_url = f"https://www.iesdouyin.com/share/video/{video_id}/"
            headers = {
                "User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 16_0 like Mac OS X)",
                "Referer": "https://www.douyin.com/",
            }
            resp = await self.client.get(share_url, headers=headers)
            text = resp.text

            # 从 HTML 中正则提取关键字段
            def _extract(pattern: str) -> str:
                m = re.search(pattern, text)
                return m.group(1) if m else ""

            title = _extract(r'"desc":"([^"]+)"')
            author = _extract(r'"nickname":"([^"]+)"')
            duration_ms = _extract(r'"duration":(\d+)')

            if not title:
                return None

            # 提取视频下载 URL（优先级: play_addr > playApi > mp4 链接）
            download_url = ""

            # play_addr.url_list 里的完整 URL
            play_addr_match = re.search(
                r'"play_addr":\{[^}]*"url_list":\["([^"]+)"', text
            )
            if play_addr_match:
                download_url = play_addr_match.group(1).replace(r"\u002F", "/")
                # 去水印: playwm → play
                download_url = download_url.replace("/playwm/", "/play/")

            # fallback: playApi
            if not download_url:
                play_api = _extract(r'"playApi":"([^"]+)"')
                if play_api:
                    play_api = play_api.replace(r"\u002F", "/")
                    if play_api.startswith("//"):
                        download_url = "https:" + play_api
                    elif not play_api.startswith("http"):
                        download_url = "https://www.douyin.com" + play_api
                    else:
                        download_url = play_api

            return VideoInfo(
                title=title,
                author=author,
                platform="douyin",
                duration=int(duration_ms) // 1000 if duration_ms else 0,
                description=title,
                url=url,
                download_url=download_url,
                tags=[],
            )
        except Exception:
            return None

    async def _ytdlp(self, url: str, platform: str) -> VideoInfo | None:
        """yt-dlp — 万能后端。"""
        try:
            proc = await asyncio.create_subprocess_exec(
                "yt-dlp",
                "--dump-json",
                "--no-download",
                "--no-warnings",
                url,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=30)

            if proc.returncode != 0:
                return None

            data = json.loads(stdout.decode())
            return VideoInfo(
                title=data.get("title", ""),
                author=data.get("uploader", "") or data.get("channel", ""),
                platform=platform or data.get("extractor", "unknown"),
                duration=int(data.get("duration", 0)),
                description=data.get("description", ""),
                url=data.get("webpage_url", url),
                download_url=data.get("url", ""),
                publish_date=data.get("upload_date", ""),
                view_count=int(data.get("view_count", 0) or 0),
                tags=data.get("tags", []) or [],
            )
        except (FileNotFoundError, asyncio.TimeoutError, json.JSONDecodeError):
            return None

    def _detect_platform(self, url: str) -> str:
        url_lower = url.lower()
        if "douyin.com" in url_lower:
            return "douyin"
        if "bilibili.com" in url_lower or "b23.tv" in url_lower:
            return "bilibili"
        if "youtube.com" in url_lower or "youtu.be" in url_lower:
            return "youtube"
        if "tiktok.com" in url_lower:
            return "tiktok"
        return "unknown"


def get_executor() -> VideoExecutor:
    """工厂函数，供 Skill 加载器调用。"""
    return VideoExecutor()
