---
name: video
version: 0.1.0
description: 下载和解析视频（抖音、B站、YouTube），提取信息并生成 wiki 页面
author: syf
tools:
  - video_download
  - video_info
  - video_to_wiki
requires:
  - yt-dlp
---

# Video Skill

## 能力
- 下载视频（无水印）
- 解析视频信息（标题、作者、时长、标签）
- 生成 wiki 页面（视频摘要）

## 支持平台

| 平台 | 工具 | 方式 | 优先级 |
|------|------|------|--------|
| 抖音 | tikwm API | HTTP API，无水印 | 1 |
| 抖音 | yt-dlp | 命令行 | 2（fallback） |
| B站 | yt-dlp | 命令行 | 1 |
| YouTube | yt-dlp | 命令行 | 1 |
| TikTok | tikwm API | HTTP API | 1 |
| 通用 | yt-dlp | 命令行 | fallback |

## 工具定义

### video_download
下载视频到本地。
- 参数: url (str, 必填)
- 输出: 下载文件路径 + 视频元信息

### video_info
解析视频信息，不下载。
- 参数: url (str, 必填)
- 输出: 视频元信息（标题、作者、时长、标签、播放量）

### video_to_wiki
完整流程: 解析视频信息 → 生成 wiki 页面。
- 参数: url (str, 必填)
- 输出: 生成的 wiki 页面路径

## 执行策略

级联尝试，按优先级：
1. 先试平台专属 API（tikwm），速度快
2. fallback 到 yt-dlp，兼容性最好

## Wiki 输出模板

```
---
title: {video_title}
tags: [video, {platform}]
source: {video_url}
created: {date}
status: seedling
---

# {video_title}

- **作者**: {author}
- **平台**: {platform}
- **时长**: {duration}
- **发布日期**: {publish_date}

## 摘要
{description}
```
