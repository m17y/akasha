# Akasha TODO

## 当前状态：v0.6 ✅

10 个 MCP tools，117 个测试，已发布到 GitHub。

| 版本 | 内容 | 状态 |
|------|------|------|
| v0.1 | 最小可用 MCP Server（搜索 + 索引） | ✅ |
| v0.2 | 模块拆分 + 增量索引 + tag 过滤 | ✅ |
| v0.3 | LLM Wiki 知识编译（ingest / save / lint） | ✅ |
| v0.4 | mkdocs-material 站点（OI-wiki 风格） | ✅ |
| v0.5 | Skill 系统 + video skill（抖音/B站/YouTube） | ✅ |
| v0.6 | 安全 / 韧性 / 可观测 | ✅ |

---

## 未来规划

### 高价值（下一步做）

- [ ] **Skill: web_clip** — 给一个 URL，自动提取正文存为 wiki 页面。场景：看到好文章一句话收藏
- [ ] **Skill: media** — 用 whisper 提取视频/音频中的语音 → 转文字 → 生成 wiki。现在 video skill 只能拿标题简介，不能提取视频里说了什么
- [ ] **GitHub Actions** — git push 后自动构建 mkdocs 站点，部署到 GitHub Pages。现在要手动 `akasha-site deploy`

### 体验优化

- [ ] **文件 watcher** — 监听 docs/ 目录变化，自动刷新索引。现在改了笔记要手动 `refresh_index`
- [ ] **Obsidian [[双链]]** — 解析 `[[page-name]]` 语法，让 wiki 页面间的链接在搜索和站点中可用
- [ ] **中文 embedding 优化** — 换 sentence-transformers 的中文模型（如 text2vec-chinese），提升中文搜索准确度
- [ ] **两阶段搜索** — 先读 index.md 粗筛定位，再向量精搜。减少噪声结果

### 长期探索

- [ ] **program.md** — AutoAgent 模式，AI 根据使用反馈自动优化 ingest/search 的 prompt
- [ ] **Code Review Agent** — 独立项目，AI 自动审查代码（参见 DESIGN.md）
