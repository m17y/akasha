# Karpathy LLM Wiki 分析

> 地址: https://gist.github.com/karpathy/442a6bf555914893e9891c11519de94f
> 作者: Andrej Karpathy (前 Tesla AI / OpenAI)
> Stars: 5000+ | Forks: 3864
> 一句话: 用 LLM 增量构建和维护个人知识 wiki，知识编译一次、持续更新，不是每次查询从零推导。

---

## 核心思想

大多数人用 LLM + 文档的方式是 RAG：上传文件 → 查询时检索 chunk → 生成回答。
这能用，但 **LLM 每次都在从零发现知识，没有累积**。

LLM Wiki 不同：LLM **增量构建和维护一个持久的 wiki**。添加新源时，LLM 不只是索引它，
而是读它、提取关键信息、**整合到已有 wiki 中** — 更新实体页面、修订主题摘要、标注矛盾。

**Wiki 是一个持久的、复利增长的知识产物。**

---

## 三层架构

| 层 | 内容 | 谁维护 |
|----|------|--------|
| Raw Sources | 原始文档（文章、论文、数据），不可变 | 你 |
| Wiki | LLM 生成的 Markdown 页面（摘要、实体、概念、对比） | LLM |
| Schema | wiki 的组织规则、命名约定、工作流 | 你和 LLM 共同演进 |

---

## 四个核心操作

### 1. Ingest（摄入）
扔一个新源进来，LLM 读取 → 讨论要点 → 写摘要页 → 更新 index → 更新相关实体/概念页 → 追加 log。
单次摄入可能触及 10-15 个 wiki 页面。

### 2. Query（查询）
问问题 → LLM 先读 index.md 定位 → 读相关页面 → 综合回答。
好回答可以 **存回 wiki 成为新页面**，让探索也累积。

### 3. Lint（健康检查）
定期让 LLM 检查: 矛盾、过时、孤立页、缺失概念页、缺失交叉引用。

### 4. 索引导航
- **index.md** — 内容导向，所有页面的目录 + 一句话摘要
- **log.md** — 时间导向，append-only 的操作记录

---

## 为什么这比 RAG 好

| RAG | LLM Wiki |
|-----|----------|
| 每次查询重新检索 | 知识已编译，直接读 wiki |
| chunk 碎片化 | 页面有完整语义 + 交叉引用 |
| 矛盾不会被发现 | 新旧矛盾被标注 |
| 综合分析每次重做 | 综合已经完成，存在 wiki 里 |
| 好回答消失在聊天记录 | 好回答存回 wiki |

---

## 为什么这能 work

> 维护知识库的累赘不是阅读和思考 — 是记账。更新交叉引用、保持摘要最新、
> 标注新旧矛盾、维护几十个页面的一致性。人类放弃 wiki 是因为维护成本增长比价值更快。
> LLM 不会无聊，不会忘记更新交叉引用，一次能触及 15 个文件。
> 维护成本接近零，所以 wiki 能持续保持更新。

---

## 评论区有价值的补充

### wiki-kb (SonicBotMan) — 防退化方案
- 加了 Schema 层: YAML frontmatter 类型校验，写入前验证
- Entity Registry: JSON 实体注册表，防止同一概念创建重复页面
- 定期 lint: 检查双向引用、图连通性

### FUNGI Framework (FBoschman) — 笔记加工流程
- 5 步处理: Frame → Unearth → Network → Grow → Interrogate
- 每条笔记必须有反驳论点（防确认偏误）
- 笔记状态: seedling / developing / mature

### Context 节省方案 (jurajskuska)
- Sandbox 拦截大输出，不进 context window
- 实测 192KB 数据中 64% 被拦截在 context 外
- Token 节省 ~31,000

### Cortex (abbacusgroup) — 形式化推理
- OWL-RL 本体论 + SPARQL 图
- 传递链推理（A 取代 B，B 取代 C → A 取代 C）
- 矛盾检测用形式逻辑，不用 LLM

---

## 与我们 AI 知识库项目的关系

Karpathy 的 LLM Wiki 理念已经融合到 `ai-knowledge-base/DESIGN.md` 中:

| Karpathy 的概念 | 我们的实现 |
|-----------------|-----------|
| 三层架构 | raw/ + wiki/ + schema.md |
| Ingest 操作 | `ingest_source` MCP tool |
| Query 回写 | `save_as_page` MCP tool |
| Lint 操作 | `lint_wiki` MCP tool |
| index.md | 两阶段搜索（index.md 粗筛 + ChromaDB 精搜） |
| log.md | append-only 时间线 |
| Obsidian 集成 | Vault 目录结构 + 推荐插件 |
