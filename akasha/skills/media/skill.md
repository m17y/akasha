---
name: media
version: 0.1.0
description: 音视频语音转文字 — 用 whisper 提取语音内容，生成文字稿或 wiki 页面
author: syf
tools:
  - media_transcribe
  - media_to_wiki
requires:
  - openai-whisper
  - ffmpeg
---

# Media Skill

## 能力
- 从音视频文件中提取语音，转为文字
- 支持本地文件和 URL（先下载再转写）
- 生成带时间戳的文字稿
- 生成 wiki 页面

## 工具定义

### media_transcribe
提取音视频中的语音，返回文字稿。
- 参数: source (str, 必填) — 本地文件路径或 URL
- 输出: 文字稿文本

### media_to_wiki
提取语音 → 生成 wiki 页面。
- 参数: source (str, 必填) — 本地文件路径或 URL, title (str, 可选) — 页面标题
- 输出: wiki 页面路径

## 执行策略

1. 如果 source 是 URL，先用 httpx 下载到临时目录
2. 用 ffmpeg 提取音频（转 wav 16kHz mono）
3. 调用 OpenAI Whisper API 或本地 whisper 模型转写
4. 返回文字稿或生成 wiki 页面
