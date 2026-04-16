---
name: pdf
version: 0.1.0
description: 提取 PDF 文件内容并生成 wiki 知识页面
tools:
  - pdf_to_wiki
  - pdf_extract
---

# PDF Skill

## 能力
- 提取 PDF 文本内容（支持文字型和扫描型 PDF）
- 用 LLM 深度整理 PDF 内容，生成结构化知识文章
- 自动保存为 wiki 页面

## 工具定义

### pdf_to_wiki
提取 PDF 内容并生成 wiki 页面。
- 参数: file_path (str, 必填) — PDF 文件路径
- 输出: 生成的 wiki 页面路径

### pdf_extract
仅提取 PDF 文本，不保存。
- 参数: file_path (str, 必填) — PDF 文件路径
- 输出: 提取的文本内容
