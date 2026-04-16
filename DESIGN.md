# Akasha — 设计文档

> 个人 AI 知识库引擎 — 语义搜索 + LLM Wiki 知识编译 + Agent + 可插拔 Skill
> 融合 Karpathy LLM Wiki 理念：知识不是每次重新检索，而是编译一次、持续更新。

---

## 一、核心理念

来自 [Karpathy LLM Wiki](https://gist.github.com/karpathy/1dd0294ef9567971c1e4348a90d69285)：

> 传统 RAG：上传文件 → 查询时检索 chunk → 生成回答。LLM 每次从零发现知识，没有累积。
>
> LLM Wiki：LLM **增量构建和维护一个持久的 wiki**。添加新源时，LLM 读它、提取关键信息、
> **整合到已有 wiki 中** — 更新概念页、修订主题摘要、标注矛盾。
> 知识编译一次，持续更新，不是每次查询都重新推导。

| 传统 RAG | LLM Wiki |
|---------|----------|
| 每次查询从零检索 | 知识已编译，直接读 wiki |
| chunk 碎片化，缺乏关联 | 页面之间有交叉引用 |
| 矛盾不会被发现 | 新旧信息矛盾会被标注 |
| 问过的好问题消失在聊天记录里 | 好回答可以存回 wiki |
| 你写，LLM 搜 | LLM 写 wiki，你管方向 |

Akasha 的定位：你写原始素材（raw），LLM 维护结构化 wiki，ChromaDB 提供向量检索兜底。

---

## 二、架构概览

```
┌─────────────────────────────────────────────────┐
│  接入层（薄壳，只做协议转换）                      │
│  ├── serve/mcp.py       MCP Server (stdio)      │
│  ├── serve/cli.py       终端交互                 │
│  └── serve/feishu.py    飞书 Bot (WebSocket)     │
├─────────────────────────────────────────────────┤
│  Agent 层（大脑）                                 │
│  ├── agent/loop.py      决策循环                 │
│  ├── agent/executor.py  执行 action              │
│  └── agent/prompts/     system prompt            │
├─────────────────────────────────────────────────┤
│  Vault 层（核心，唯一入口）                        │
│  vault.py → search / read / ingest              │
│             / save_page / lint / ask             │
│  post_save hook → 概念/实体提取 → 种子页面创建    │
├─────────────────────────────────────────────────┤
│  能力层                                          │
│  ├── compiler.py        知识编译                 │
│  ├── storage/           文件 + 向量索引           │
│  │   ├── files.py       文件系统操作              │
│  │   └── index.py       ChromaDB 向量索引         │
│  ├── skills/            可插拔扩展                │
│  │   ├── video/         视频下载 + 分析           │
│  │   ├── web_clip/      网页剪藏                 │
│  │   └── media/         音视频转写(faster-whisper)│
│  └── llm.py             LLM 客户端               │
├─────────────────────────────────────────────────┤
│  站点层                                          │
│  site/                                          │
│  ├── mkdocs_config.py   自动生成 mkdocs.yml      │
│  ├── wikilinks.py       [[双链]] → HTML 链接     │
│  ├── graph.py           知识图谱数据 (AntV G6)   │
│  └── deploy.py          部署到 GitHub Pages      │
└─────────────────────────────────────────────────┘
```

核心设计：**Vault 是唯一入口**。所有接入层都调同一个 Vault 实例，不直接操作底层模块。

---

## 三、知识流转

### 视频链接 → 知识文档

```
视频链接（抖音/B站/YouTube）
  → skills/video 下载视频
  → skills/media 提取音频 → faster-whisper 转写
  → LLM 深度分析（不是原文粘贴，而是结构化整理）
  → vault.save_page() 保存文章
  → post_save hook 自动触发
    → 提取概念/实体
    → 创建种子页面
    → 更新知识图谱
```

### 网页链接 → 知识文档

```
网页链接
  → skills/web_clip 抓取正文
  → LLM 深度整理（提炼要点、结构化重写）
  → vault.save_page() 保存文章
  → post_save hook 自动触发
```

### ingest → 知识编译

```
原始素材（raw/ 下的文件）
  → compiler.py 读取内容
  → LLM 提取关键信息（概念、实体、关系、结论）
  → 更新/创建 wiki 页面
  → 更新 index.md + log.md
  → 更新向量索引
```

单次 ingest 可能触及 5-15 个 wiki 页面 — 更新交叉引用、标注矛盾、建立关联。

---

## 四、Vault Hook 机制

Vault 的 `save_page()` 方法在保存文件后触发 **post_save hook**，自动完成：

1. **概念/实体提取** — LLM 分析文章内容，提取提到的概念和实体
2. **种子页面创建** — 为尚未存在的概念/实体创建 wiki 种子页面（status: seedling）
3. **图谱更新** — 更新知识图谱中的节点和边关系
4. **交叉引用** — 在相关页面中添加 `[[双链]]` 引用
5. **向量索引** — 将新内容索引到 ChromaDB

Hook 机制确保每次内容变更都能自动扩展知识网络，无需手动维护。

---

## 五、概念分类

LLM 在提取概念/实体时自动分类，写入页面 frontmatter：

```yaml
---
title: Agent Loop
type: concept          # concept 或 entity
category: 技术概念      # 分类
status: seedling       # seedling / developing / mature
related: [MCP, LLM]
---
```

**type 分类：**

| type | 说明 | 示例 |
|------|------|------|
| `concept` | 抽象概念、方法论 | Agent Loop、RAG、Harness Engineering |
| `entity` | 具体事物 | AutoAgent、GPT-4o、Karpathy |

**category 分类（concept）：**

| category | 示例 |
|----------|------|
| 技术概念 | Agent Loop、Embedding、MCP |
| 方法论 | Harness Engineering、TDD |
| 设计模式 | 级联 fallback、两阶段搜索 |
| 领域知识 | 向量数据库、知识图谱 |

**category 分类（entity）：**

| category | 示例 |
|----------|------|
| 人物 | Karpathy、Andrej |
| 公司/组织 | Anthropic、OpenAI |
| 项目/产品 | AutoAgent、ChromaDB |
| 工具 | yt-dlp、mkdocs-material |

---

## 六、知识图谱

站点内置交互式知识图谱，使用 **AntV G6** 渲染。

### 数据生成

`site/graph.py` 扫描 wiki/ 下所有页面：
- 解析 frontmatter 中的 `type`、`category`、`related`
- 解析正文中的 `[[双链]]` 引用
- 生成节点（页面）和边（引用关系）的 JSON 数据

### 可视化

- 节点按 type/category 着色
- 节点大小按入链数量（被引用次数）
- 力导向布局，支持拖拽
- 点击节点 → 侧边栏显示页面摘要 + 链接
- 搜索高亮关联节点

### 集成

知识图谱作为 MkDocs Material 站点的一个页面嵌入，`mkdocs_config.py` 自动配置。

---

## 七、Skill 系统

**Skill 的核心是 Markdown，不是 Python。**

每个 Skill 包的灵魂是 `skill.md` — 定义能力、工具链、prompt、输出模板。
Python 代码（`executor.py`）只是薄执行层 — 调 API、跑命令、返回结果。

### 目录结构

```
akasha/skills/your_skill/
├── skill.md        ← 定义名称、描述、工具列表 + Agent 能力说明
└── executor.py     ← 执行逻辑，提供 get_executor() 函数
```

### 加载机制

Agent 启动时扫描 `skills/` 下所有子目录 → 找到 `skill.md` → 解析 frontmatter → 注册工具。
skill.md 的完整内容作为 Agent 的能力说明书，让 Agent 理解自己有什么扩展能力。

### 现有 Skill

| Skill | 说明 |
|-------|------|
| `video/` | 视频下载 + 分析（tikwm API + yt-dlp，级联 fallback） |
| `web_clip/` | 网页剪藏（HTML 解析 → Markdown → LLM 整理） |
| `media/` | 音视频转写（ffmpeg + faster-whisper） |

### 新增 Skill

添加目录 + 写 skill.md + 写 executor.py → 重启即生效，无需改任何现有代码。

---

## 八、部署方式

### uv（开发 / 个人使用）

```bash
uv tool install --from git+https://github.com/m17y/akasha akasha
akasha start
```

### Docker

```bash
docker compose up -d
```

镜像 `ghcr.io/m17y/akasha:latest`，GitHub Actions 自动构建。
数据持久化在 Docker volume 中。支持群晖 NAS。

### pm2（后台常驻）

```bash
pm2 start ~/akasha/ecosystem.config.js
pm2 save && pm2 startup  # 开机自启
```

环境变量在 `~/.zshrc` 中配置，ecosystem.config.js 通过 `process.env` 读取。

---

## 九、约束

### 做什么

- 三层知识：raw（你写）→ wiki（LLM 维护）→ schema（规则）
- 通过 MCP / CLI / 飞书提供检索 + 知识维护 + Skill 调用
- index.md + ChromaDB 双模检索
- ingest 时自动更新交叉引用和标注矛盾
- post_save hook 自动提取概念/实体并创建种子页面
- LLM 深度整理内容（不是原文粘贴）
- AntV G6 交互式知识图谱
- mkdocs-material 生成静态站点，可发布到 GitHub Pages
- 可插拔 Skill 系统（视频下载/解析、网页剪藏、音视频转写）

### 不做什么

- 不做自定义 Web UI（mkdocs-material + AntV G6 够用）
- 不做多用户（个人用）
- 不自动修改 raw/ 下的文件（raw 是 source of truth，不可变）
- Skill 不做视频编辑/转码（只做下载、转写、信息提取、生成 wiki）
