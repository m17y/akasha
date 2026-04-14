# TODO LIST

> 原则: 砍掉 80%，只做一个项目。先跑通再优化。
> 每个版本只做最小可用的东西，跑通了再加下一个。

---

## 当前进度

- [x] 调研 Harness Engineering 项目推荐
- [x] 深度分析 AutoAgent
- [x] 深度分析 Code Review Agent
- [x] 分析 Karpathy LLM Wiki
- [x] 分析六层 Agent 架构（第30章）
- [x] 设计 AI 知识库 DESIGN.md
- [x] 设计 Code Review Agent DESIGN.md
- [x] **写第一行代码**
- [x] **v0.1 完成** — 单文件 MCP Server (356行)，4 个 tools，本地 embedding

---

## v0.1 — 最小可用知识库 MCP Server ✅

- [x] 创建 `ai-knowledge-base/pyproject.toml`
- [x] 创建 `ai-knowledge-base/knowledge_mcp/server.py`（单文件，356行）
  - [x] 启动时扫描 vault 下所有 .md 文件
  - [x] 按 `#` `##` `###` 标题切分成 chunks
  - [x] ChromaDB 内置 embedding（all-MiniLM-L6-v2，无需 API Key）
  - [x] 存入 ChromaDB（本地持久化）
  - [x] 实现 `search_knowledge` MCP tool
- [x] 实现 `list_notes` / `read_note` / `refresh_index` tools
- [x] 23 个单元测试全部通过（tests/test_server.py）
- [ ] 注册到 Claude Code / OpenCode 的 MCP 配置
- [ ] 验证: 端到端搜索测试

---

## v0.2 — 模块拆分 + 基础完善 ✅

- [x] 拆分模块: config.py / chunker.py / store.py / indexer.py
- [x] 重构 server.py — 使用拆分后的模块
- [x] 增量更新索引（基于文件修改时间 + .index_meta.json 记录）
- [x] frontmatter 增强（提取 tags、date、source、status 用于搜索过滤）
- [x] 搜索支持 tag 过滤（`search_knowledge(query, tags="hive,sql")`）
- [x] `refresh_index` 支持 force 参数（强制全量/增量）
- [x] 删除文件自动清理索引中的对应 chunks
- [x] pyproject.toml 升级到 v0.2.0，修复 deprecated 配置
- [x] 60 个测试全部通过（test_chunker / test_store / test_indexer / test_server）

---

## v0.3 — LLM Wiki 知识维护 ✅

从"被动检索"升级为"主动编译"。

- [x] 创建 vault 三层目录结构（raw/ + wiki/ + schema.md）
- [x] 迁移 5 篇分析文档到 raw/（analysis/ + notes/）
- [x] 编写 schema.md（wiki 规则、页面格式、命名约定）
- [x] 创建 index.md + log.md
- [x] config.py 添加 LLM 配置（api_key / base_url / model）
- [x] 创建 llm.py — LLM 客户端封装（OpenAI 兼容）
- [x] 创建 ingester.py — 知识摄入器（Karpathy LLM Wiki 核心）
- [x] 实现 `ingest_source` tool（摄入 → LLM 提取概念 → 创建/更新 wiki 页面）
- [x] 实现 `save_as_page` tool（好回答存为 wiki 页面）
- [x] 实现 `lint_wiki` tool（健康检查: frontmatter/孤立/引用/空页面）
- [x] pyproject.toml 升级到 v0.3.0，添加 openai/httpx 依赖
- [x] 79 个测试全部通过（含 19 个新增 ingester 测试）
- [ ] 两阶段搜索优化（index.md 粗筛 + ChromaDB 精搜）— 移至后续版本

---

## v0.4 — mkdocs-material 站点 ✅

- [x] 创建 site.py — 根据 vault 路径动态生成 mkdocs.yml
- [x] mkdocs.yml 和 site/ 构建产物放在项目目录内
- [x] 配置中文搜索、暗色模式/亮色模式切换、代码高亮、代码复制
- [x] 自动扫描 vault 目录生成导航（raw/ + wiki/ + schema + log）
- [x] `knowledge-site serve` 本地预览验证通过
- [x] `knowledge-site build` 构建静态站点验证通过
- [x] `knowledge-site deploy` 发布到 GitHub Pages（命令就绪）
- [x] 79 个测试全部通过

---

## v0.5 — Skill 系统 ✅

可插拔的能力扩展。Skill 的核心是 Markdown，Python 只是薄执行层。

- [x] skills/__init__.py — SkillDef 数据类 + discover_skills 扫描加载器
- [x] Skill 自动发现 + MCP tool 动态注册（server.py 启动时扫描 skills/）
- [x] video Skill:
  - [x] skills/video/skill.md — 能力定义、工具链、wiki 模板
  - [x] skills/video/executor.py — tikwm API + yt-dlp 双后端
  - [x] `video_download` tool — 下载视频到本地
  - [x] `video_info` tool — 获取视频信息（不下载）
  - [x] `video_to_wiki` tool — 解析视频 → 生成 wiki 页面
- [x] CLI 更新: `akasha help/init/status` 子命令
- [x] `uv tool install` 全局安装支持
- [x] 99 个测试全部通过（含 20 个新增 skill 测试）

---

## v0.6 — 六层架构补全 ✅

- [x] L4 安全:
  - [x] ingester.py `_validate_write_path()` — 拒绝写入 raw/、拒绝 `..` 穿越、resolve 验证
  - [x] save_as_page category 白名单校验
  - [x] server.py read_note 路径安全 — 先校验越权再检查存在，修复 startswith 前缀碰撞
- [x] L5 韧性:
  - [x] llm.py — `max_retries=3` 自动重试 (429/500/502/503)，`timeout=120s`
- [x] L6 可观测:
  - [x] events.py — 结构化事件日志 (`emit()` + `Timer`)
  - [x] 埋点: search_query/result, ingest_started/completed/failed, security_blocked
- [x] 截断时注入元信息 — 引导用户 `read_note(source)` 查看完整内容
- [x] read_note 支持 offset 分页读取大文件
- [x] 117 个测试全部通过（含 16 个新增安全/韧性/可观测测试）

---

## 以后再说（不排期）

- [ ] Code Review Agent 项目（另一个独立项目）
- [ ] 本地 embedding fallback（sentence-transformers）
- [ ] 文件 watcher（fswatch），自动刷新索引
- [ ] Obsidian [[双链]] 解析
- [ ] Skill: web_clip（网页剪藏）
- [ ] Skill: media（音视频转文字）
- [ ] GitHub Actions 自动构建 mkdocs
- [ ] program.md（AutoAgent 模式，AI 自动优化 prompt）

---

## 已完成的文档

| 文件 | 内容 |
|------|------|
| `AI调研/harness-engineering.md` | Harness Engineering 项目推荐 Top 10 |
| `AI调研/autoagent-analysis.md` | AutoAgent 深度分析 |
| `AI调研/code-review-agent-analysis.md` | Code Review Agent 深度分析 |
| `AI调研/six-layer-agent-architecture.md` | 六层 Agent 架构分析 |
| `karpathy-llm-wiki-analysis.md` | Karpathy LLM Wiki 分析 |
| `ai-knowledge-base/DESIGN.md` | AI 知识库完整设计 |
| `code-review-agent/DESIGN.md` | Code Review Agent 设计 |
