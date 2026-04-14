# Akasha TODO

## 当前状态：v0.6 ✅

10 个 MCP tools，117 个测试，已发布到 [GitHub](https://github.com/m17y/akasha)。

| 版本 | 内容 | 状态 |
|------|------|------|
| v0.1 | 最小可用 MCP Server（搜索 + 索引） | ✅ |
| v0.2 | 模块拆分 + 增量索引 + tag 过滤 | ✅ |
| v0.3 | LLM Wiki 知识编译（ingest / save / lint） | ✅ |
| v0.4 | mkdocs-material 站点（OI-wiki 风格） | ✅ |
| v0.5 | Skill 系统 + video skill（抖音/B站/YouTube） | ✅ |
| v0.6 | 安全 / 韧性 / 可观测 | ✅ |

---

## v0.7 — 高价值功能 ✅

- [x] **Skill: web_clip** — 网页剪藏（`web_clip_save` / `web_clip_read`）
- [x] **Skill: media** — 音视频转文字（`media_transcribe` / `media_to_wiki`，whisper CLI + API）
- [x] **GitHub Actions** — CI 测试 + GitHub Pages 自动部署
- [x] 140 个测试全部通过

---

## 未来

- [ ] 文件 watcher — 监听 docs/ 变化，自动刷新索引
- [ ] Obsidian [[双链]] 解析
- [ ] 中文 embedding 优化（text2vec-chinese）
- [ ] 两阶段搜索（index.md 粗筛 + 向量精搜）
- [ ] program.md — AutoAgent 模式，AI 自动优化 prompt
