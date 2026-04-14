# Akasha TODO

## 历史版本

| 版本 | 内容 | 状态 |
|------|------|------|
| v0.1 | 最小可用 MCP Server（搜索 + 索引） | ✅ |
| v0.2 | 模块拆分 + 增量索引 + tag 过滤 | ✅ |
| v0.3 | LLM Wiki 知识编译（ingest / save / lint） | ✅ |
| v0.4 | mkdocs-material 站点（OI-wiki 风格） | ✅ |
| v0.5 | Skill 系统 + video skill（抖音/B站/YouTube） | ✅ |
| v0.6 | 安全 / 韧性 / 可观测 | ✅ |
| v0.7 | web_clip + media skill + GitHub Actions CI | ✅ |

---

## v1.0 — 架构重构：AI 知识库引擎 + Agent ✅

从"MCP Server 暴露一堆 tool"重构为"Vault 核心 + Agent 决策 + 多接入层"。
198 个测试全部通过。

### Phase 1: 基础设施 — Vault 核心 ✅

- [x] 1.1 config.py 保持不变
- [x] 1.2 创建 `storage/files.py` — 文件读写 + 路径安全校验
- [x] 1.3 创建 `storage/index.py` — 向量索引（合并 chunker + store + indexer）
- [x] 1.4 创建 `vault.py` — Vault 类，统一入口
- [x] 1.5 测试 — 24 个测试通过

### Phase 2: 知识编译 — Compiler ✅

- [x] 2.1 创建 `compiler.py`（从 ingester.py 迁移，改为依赖 FileStore）
- [x] 2.2 Vault 集成 compiler（vault.ingest / vault.save_page / vault.lint）
- [x] 2.3 测试 — 15 个测试通过

### Phase 3: Skills — 可插拔扩展能力 ✅

- [x] 3.1 重构 `skills/__init__.py` — SkillRegistry 统一管理
- [x] 3.2 skills/video、web_clip、media 保持不变
- [x] 3.3 Vault 集成 skills（vault.load_skills / vault.execute_skill / vault.get_skill_prompts）
- [x] 3.4 测试 — 22 个旧测试全部通过

### Phase 4: Agent ✅

- [x] 4.1 创建 `agent/prompts/system.md` — Agent 身份 + 工具说明
- [x] 4.2 创建 `agent/executor.py` — 执行 action，调用 Vault 方法
- [x] 4.3 创建 `agent/loop.py` — Agent Loop（observe → think → act）
- [x] 4.4 Vault 集成 Agent（vault.ask / vault.create_agent）
- [x] 4.5 测试 — 19 个测试通过

### Phase 5: 接入层 ✅

- [x] 5.1 创建 `serve/mcp.py` — MCP Server（ask + 细粒度 tools 向后兼容）
- [x] 5.2 创建 `serve/cli.py` — 命令行
- [x] 5.3 创建 `serve/site.py` — 站点（复用 site.py）
- [x] 5.4 更新 pyproject.toml（v1.0.0，新入口点）

### Phase 6: 收尾 ✅

- [x] 6.1 全量测试 — 198 passed
- [x] 6.2 更新 TODO-LIST.md
- [x] 6.3 旧文件保留（server.py 等向后兼容，后续版本清理）

---

## 未来

- [ ] Agent memory — 工作记忆 + 长期记忆（记住用户偏好和操作历史）
- [ ] 文件 watcher — 监听 docs/ 变化，Agent 自动摄入
- [ ] Obsidian [[双链]] 解析
- [ ] 中文 embedding 优化（text2vec-chinese）
- [ ] 两阶段搜索（index.md 粗筛 + 向量精搜）
- [ ] Web UI — HTTP API 接入层
- [ ] 清理旧文件（server.py / chunker.py / store.py / indexer.py / ingester.py）
