---
name: web_clip
version: 0.1.0
description: 网页剪藏 — 提取网页正文，保存为知识库 wiki 页面
author: syf
tools:
  - web_clip_save
  - web_clip_read
---

# Web Clip Skill

## 能力
- 提取网页正文（去除广告、导航、侧边栏）
- 转换为干净的 Markdown
- 保存为 wiki 页面（带 frontmatter）
- 仅读取网页内容（不保存）

## 工具定义

### web_clip_save
提取网页正文并保存为 wiki 页面。
- 参数: url (str, 必填), category (str, 默认 "articles")
- 输出: 保存的 wiki 页面路径

### web_clip_read
提取网页正文，返回 Markdown，不保存。
- 参数: url (str, 必填)
- 输出: Markdown 格式的网页正文

## 提取策略

级联尝试：
1. 用 httpx 获取 HTML
2. 用内置提取器解析正文（基于标签权重算法）
3. 生成 Markdown（标题、段落、列表、代码块、链接、图片）

## Wiki 输出模板

```
---
title: {page_title}
tags: [web-clip, {domain}]
source: {url}
created: {date}
status: seedling
---

# {page_title}

> 来源: [{url}]({url})

{content}
```
