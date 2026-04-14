# AI 知识库 — 设计文档

> Obsidian 写笔记 + LLM 维护 Wiki + MCP Server 做 AI 检索 + mkdocs-material 发布静态站点
> 融合 Karpathy LLM Wiki 理念：知识不是每次重新检索，而是编译一次、持续更新。
> 可插拔 Skill 系统：视频下载/解析、网页剪藏、内容提取等能力按需加载。

---

## 一、要解决的问题

你有一堆学习笔记（Harness Engineering、MCP、Agent 架构分析...），散落在 Markdown 文件里。

**痛点**:
- 写了但记不住在哪个文件里
- grep 只能搜关键词，搜不到语义相关的内容
- 想在写代码时顺手查笔记，但要切换到文件浏览器去翻
- 知识之间的关联靠你脑子记，没有自动交叉引用
- 每次问 LLM 都是从零检索，之前的综合分析不会累积

**目标**:
- 用 Obsidian 写和浏览笔记（好用的编辑器 + 双链 + 图谱）
- 用 Git 管理版本（你已经在做了）
- 用 MCP Server 提供 AI 检索 + 知识维护
- **知识会累积** — 每次 ingest 新源，wiki 自动更新交叉引用、标注矛盾、建立关联

---

## 二、核心理念（来自 Karpathy LLM Wiki）

> 传统 RAG：上传文件 → 查询时检索 chunk → 生成回答。LLM 每次从零发现知识，没有累积。
>
> LLM Wiki：LLM **增量构建和维护一个持久的 wiki**。添加新源时，LLM 读它、提取关键信息、
> **整合到已有 wiki 中** — 更新实体页面、修订主题摘要、标注矛盾。
> 知识编译一次，持续更新，不是每次查询都重新推导。

**关键区别**：

| 传统 RAG | LLM Wiki |
|---------|----------|
| 每次查询从零检索 | 知识已编译，直接读 wiki |
| chunk 碎片化，缺乏关联 | 页面之间有交叉引用 |
| 矛盾不会被发现 | 新旧信息矛盾会被标注 |
| 问过的好问题消失在聊天记录里 | 好回答可以存回 wiki |
| 你写，LLM 搜 | LLM 写 wiki，你管方向 |

**本项目的定位**：两者结合 — 你用 Obsidian 写原始笔记（raw），LLM 维护结构化 wiki，
ChromaDB 提供向量检索兜底。

---

## 三、三层架构

```
┌─────────────────────────────────────────────────────────────┐
│                                                             │
│  Layer 1: Raw Sources（原始素材，不可变）                     │
│  ──────────────────────────────────────                     │
│  你用 Obsidian 写的笔记、剪藏的文章、分析文档                 │
│  LLM 只读不改。这是你的 source of truth。                    │
│                                                             │
│  vault/                                                     │
│  ├── raw/                    原始素材目录                     │
│  │   ├── articles/           剪藏的文章                      │
│  │   ├── notes/              你的手写笔记                    │
│  │   └── analysis/           项目分析（如 autoagent 分析）    │
│  │                                                          │
│  ├────────────────────────────────────────────────────────  │
│                                                             │
│  Layer 2: Wiki（LLM 维护，结构化知识）                       │
│  ────────────────────────────────────                       │
│  LLM 生成和维护的页面。交叉引用已建立，矛盾已标注。           │
│  你读它；LLM 写它。                                          │
│                                                             │
│  ├── wiki/                   LLM 维护的 wiki 页面            │
│  │   ├── concepts/           概念页（Agent Loop, MCP, ...）  │
│  │   ├── entities/           实体页（项目、工具、人物）        │
│  │   ├── comparisons/        对比页（AutoAgent vs Code Review）│
│  │   └── synthesis/          综合分析页                      │
│  ├── index.md                目录（所有页面 + 一句话摘要）     │
│  ├── log.md                  时间线（append-only）           │
│  │                                                          │
│  ├────────────────────────────────────────────────────────  │
│                                                             │
│  Layer 3: Schema（规则，你和 LLM 共同维护）                  │
│  ──────────────────────────────────────                     │
│  告诉 LLM 这个 wiki 怎么组织、什么规范、什么工作流。         │
│                                                             │
│  └── schema.md               wiki 规则和约定                 │
│                                                             │
└─────────────────────────────────────────────────────────────┘
                         │
                         │ MCP Server 读写
                         ▼
┌─────────────────────────────────────────────────────────────┐
│  knowledge-mcp (MCP Server)                                  │
│                                                             │
│  7 个 tools:                                                 │
│  ├── search_knowledge  — 语义搜索（index.md 粗筛 + 向量精搜）│
│  ├── list_notes        — 列出笔记                            │
│  ├── read_note         — 读笔记全文                          │
│  ├── ingest_source     — 摄入新源 → 更新 wiki + index        │
│  ├── save_as_page      — 把好回答存为 wiki 页                │
│  ├── lint_wiki         — 健康检查（矛盾、孤立页、缺失引用）  │
│  └── refresh_index     — 刷新向量索引                        │
│                                                             │
│  存储:                                                       │
│  ├── ChromaDB（本地向量库，语义检索兜底）                     │
│  └── index.md（目录，LLM 优先读这个定位）                    │
└──────────────────────┬──────────────────────────────────────┘
                       │ stdio
                       ▼
              Claude Code / Cursor
```

---

## 四、技术选择

| 维度 | 选择 | 理由 |
|------|------|------|
| 笔记编辑 | Obsidian | 最好的 Markdown 编辑器，双链/图谱/社区插件 |
| 笔记格式 | Markdown | 纯文本，Git 友好，Obsidian 原生 |
| 版本管理 | Git | 你已经在用 |
| MCP 框架 | `mcp` SDK + `FastMCP` | 和你的 kyuubi/meta 一致 |
| 向量数据库 | ChromaDB | 纯 Python，本地运行，零部署，适合个人用 |
| Embedding | OpenAI `text-embedding-3-small` 或 本地 `sentence-transformers` | 二选一 |
| 文档切分 | 按标题层级切分 | Markdown 天然有结构，按 `#` `##` 切 |
| 包管理 | `uv` + `pyproject.toml` | 和现有项目一致 |

### Embedding 方案

| 方案 | 优点 | 缺点 |
|------|------|------|
| **OpenAI API** (`text-embedding-3-small`) | 效果好，1536 维，便宜 | 需要 API Key，有网络依赖 |
| **本地** (`all-MiniLM-L6-v2`) | 免费，离线可用，384 维 | 效果稍差，首次加载慢 |

建议: **先用 OpenAI API**，后续加本地 fallback。

---

## 五、项目结构

```
ai-knowledge-base/
├── DESIGN.md                  -- 本文件（架构设计）
├── schema.md                  -- Wiki 规则（告诉 LLM 怎么维护 wiki）
├── mkdocs.yml                 -- mkdocs-material 配置
├── pyproject.toml             -- 依赖
├── knowledge_mcp/
│   ├── __init__.py
│   ├── server.py              -- MCP Server 入口（FastMCP + tools）
│   ├── ingester.py            -- 摄入（读源 → 更新 wiki → 更新 index）
│   ├── indexer.py             -- 文档索引（扫描 → 切分 → embedding → 存储）
│   ├── chunker.py             -- Markdown 切分器（按标题层级）
│   ├── embedder.py            -- Embedding 抽象（OpenAI / 本地）
│   ├── store.py               -- 向量存储（ChromaDB 封装）
│   └── config.py              -- 配置
├── skills/                    -- 可插拔 Skill 包目录
│   ├── __init__.py            -- Skill 加载器（扫描 skill.md → 注册）
│   ├── base.py                -- Skill 基类 + SkillResult 定义
│   ├── executor.py            -- 薄执行层（读 skill.md → 解析 → 调工具）
│   ├── video/                 -- 视频 Skill 包
│   │   ├── skill.md           -- 核心: Skill 定义（prompt + 规则 + 工具链 + 参数）
│   │   ├── executor.py        -- 薄执行层（调 tikwm API / yt-dlp）
│   │   └── README.md          -- 使用说明
│   ├── web_clip/              -- 网页剪藏 Skill 包（后续）
│   │   ├── skill.md
│   │   ├── executor.py
│   │   └── README.md
│   └── media/                 -- 媒体处理 Skill 包（后续）
│       ├── skill.md
│       ├── executor.py
│       └── README.md
└── tests/
    ├── test_chunker.py
    ├── test_indexer.py
    └── test_skills/
        ├── test_video.py
        └── test_registry.py
```

每个 Skill 是独立的包（package），有自己的目录、配置、README。
好处：独立开发、独立测试、可选安装、第三方可扩展。

---

## 六、核心操作

### 6.1 Ingest（摄入）— 最关键的操作

你扔一个新源进来，LLM 不只是索引它，而是整合到 wiki 里：

```
你: "摄入 raw/analysis/autoagent-analysis.md"

MCP Server:
  1. 读原始文件
  2. 提取关键信息（概念、实体、设计模式、结论）
  3. 更新/创建 wiki 页面:
     - wiki/concepts/agent-loop.md      ← 更新 Agent Loop 概念页
     - wiki/concepts/harness-engineering.md ← 更新交叉引用
     - wiki/entities/autoagent.md       ← 创建 AutoAgent 实体页
     - wiki/comparisons/autoagent-vs-code-review.md ← 创建对比页
  4. 更新 index.md（新增页面条目）
  5. 追加 log.md（记录本次摄入）
  6. 更新 ChromaDB 向量索引

单次 ingest 可能触及 5-15 个 wiki 页面。
```

### 6.2 Query（查询）— 两阶段搜索

```
你: "Harness Engineering 有哪些核心设计模式？"

MCP Server:
  Stage 1: 读 index.md → 找到候选页面（快，省 token）
  Stage 2: 对候选页面做向量搜索精排（准）
  → 返回相关段落 + 来源标注
```

### 6.3 Save（回写）— 好回答不丢失

```
你觉得 Claude 的回答很好，值得保存:
"把这个关于 Agent Loop 设计模式的总结存为 wiki 页"

MCP Server:
  1. 创建 wiki/synthesis/agent-loop-patterns.md
  2. 更新 index.md
  3. 追加 log.md
  4. 更新向量索引
```

### 6.4 Lint（健康检查）

```
你: "检查一下 wiki 的健康状态"

MCP Server 检查:
  - 页面之间的矛盾（新旧信息冲突）
  - 孤立页面（没有入链的页面）
  - 提到了但没有独立页面的重要概念
  - 缺失的交叉引用
  - 过时的摘要（源文件已更新但 wiki 页没更新）
→ 返回问题清单 + 修复建议
```

---

## 七、模块设计

### 7.1 Markdown 切分器 (chunker.py)

```python
@dataclass
class Chunk:
    source_file: str          # 来源文件路径
    heading_path: str         # 标题层级路径，如 "autoagent > 设计模式 > Agent Loop"
    content: str              # chunk 文本内容
    start_line: int           # 在原文件中的起始行号
    metadata: dict            # 额外元数据（frontmatter 中的 tags 等）

def split_markdown(file_path: Path) -> list[Chunk]:
    """按 Markdown 标题层级切分。

    规则:
    - 以 ## (h2) 为主要切分点
    - 每个 chunk 包含标题 + 其下的内容，直到下一个同级或更高级标题
    - chunk 过长(>1000 tokens) 时，在段落边界进一步切分
    - chunk 过短(<50 tokens) 时，合并到前一个 chunk
    - 保留 Obsidian frontmatter (YAML) 作为 metadata
    - 保留标题层级路径，便于检索时展示上下文
    """
```

### 7.2 Embedding 抽象 (embedder.py)

```python
class Embedder(ABC):
    @abstractmethod
    async def embed(self, texts: list[str]) -> list[list[float]]:
        """批量生成 embedding 向量。"""

    @abstractmethod
    def dimension(self) -> int:
        """返回向量维度。"""

class OpenAIEmbedder(Embedder):
    """调 OpenAI text-embedding-3-small，1536 维。"""

class LocalEmbedder(Embedder):
    """本地 sentence-transformers，all-MiniLM-L6-v2，384 维。"""
```

### 7.3 向量存储 (store.py)

```python
class VectorStore:
    """ChromaDB 封装。"""

    def __init__(self, persist_dir: Path, collection_name: str = "knowledge"):
        ...

    def upsert(self, chunks: list[Chunk], embeddings: list[list[float]]):
        """写入或更新。用 source_file + start_line 做去重 ID。"""

    def search(self, query_embedding: list[float], top_k: int = 5) -> list[SearchResult]:
        """语义搜索，返回最相似的 chunks。"""

    def delete_by_file(self, file_path: str):
        """删除某个文件的所有 chunks（用于增量更新）。"""

@dataclass
class SearchResult:
    chunk: Chunk
    score: float              # 相似度分数 0~1
```

### 7.4 摄入器 (ingester.py) — 新增模块

```python
class Ingester:
    """读原始源 → 提取知识 → 整合到 wiki。

    这是 Karpathy LLM Wiki 的核心: 不只是索引，而是编译知识。
    """

    def __init__(self, vault_path: Path, llm: LlmClient):
        self.raw_dir = vault_path / "raw"
        self.wiki_dir = vault_path / "wiki"
        self.index_path = vault_path / "index.md"
        self.log_path = vault_path / "log.md"

    async def ingest(self, source_path: Path) -> IngestResult:
        """摄入单个源文件。

        流程:
        1. 读取源文件内容
        2. 调 LLM 提取关键信息（概念、实体、关系、结论）
        3. 对每个概念/实体，检查 wiki 中是否已有页面:
           - 有 → 读取现有页面，调 LLM 合并新信息
           - 没有 → 调 LLM 创建新页面
        4. 更新 index.md（新增/更新条目）
        5. 追加 log.md
        6. 返回更新了哪些页面
        """

    async def save_as_page(self, title: str, content: str, category: str = "synthesis") -> str:
        """把一段内容存为 wiki 页面。

        用途: 把 LLM 的好回答保存下来，让知识不消失在聊天记录里。
        """

    async def lint(self) -> list[LintIssue]:
        """健康检查。

        检查:
        - 矛盾: 不同页面对同一事实的描述不一致
        - 孤立: 没有入链的页面
        - 缺失: 被多次提到但没有独立页面的概念
        - 过时: 源文件已更新但 wiki 页面没跟上
        """

@dataclass
class IngestResult:
    source_file: str
    pages_created: list[str]
    pages_updated: list[str]
    concepts_extracted: list[str]

@dataclass
class LintIssue:
    type: str                  # "contradiction" / "orphan" / "missing" / "stale"
    page: str
    description: str
    suggestion: str
```

### 7.5 文档索引器 (indexer.py)

```python
class Indexer:
    """扫描 vault → 切分 → embedding → 存储。"""

    def __init__(self, vault_path: Path, embedder: Embedder, store: VectorStore):
        ...

    async def index_all(self) -> IndexStats:
        """全量索引（raw/ + wiki/ 都索引）。首次启动时调用。"""

    async def index_file(self, file_path: Path) -> int:
        """索引单个文件。返回 chunk 数量。"""

    async def refresh(self) -> IndexStats:
        """增量更新。只处理上次索引后修改过的文件。"""

@dataclass
class IndexStats:
    total_files: int
    files_indexed: int
    files_skipped: int
    total_chunks: int
    duration_seconds: float
```

### 7.6 MCP Server (server.py)

```python
from mcp.server.fastmcp import FastMCP

mcp = FastMCP("knowledge")

# ── 查询类 ──

@mcp.tool()
async def search_knowledge(
    query: str,
    top_k: int = 5,
) -> str:
    """从知识库中语义搜索。

    两阶段: 先读 index.md 找候选，再向量精搜。

    Args:
        query: 搜索问题，用自然语言描述
        top_k: 返回最相关的结果数量
    """
    ...

@mcp.tool()
async def list_notes(category: str = "all") -> str:
    """列出知识库中的笔记/页面。

    Args:
        category: 过滤类别 (all/raw/wiki/concepts/entities)
    """
    ...

@mcp.tool()
async def read_note(file_path: str) -> str:
    """读取某篇笔记或 wiki 页面的完整内容。

    Args:
        file_path: 相对于 vault 根目录的路径
    """
    ...

# ── 知识维护类 ──

@mcp.tool()
async def ingest_source(file_path: str) -> str:
    """摄入一个原始源文件到知识库。

    LLM 会读取内容，提取关键信息，更新/创建相关 wiki 页面，
    更新索引和交叉引用。单次摄入可能触及 5-15 个 wiki 页面。

    Args:
        file_path: raw/ 目录下的源文件路径
    """
    ...

@mcp.tool()
async def save_as_page(title: str, content: str, category: str = "synthesis") -> str:
    """把一段有价值的内容保存为 wiki 页面。

    用途: 保存好的回答、分析、对比，让知识不消失在聊天记录里。

    Args:
        title: 页面标题
        content: 页面内容（Markdown）
        category: 分类 (concepts/entities/comparisons/synthesis)
    """
    ...

@mcp.tool()
async def lint_wiki() -> str:
    """Wiki 健康检查。

    检查矛盾、孤立页、缺失引用、过时内容，返回问题清单和修复建议。
    """
    ...

@mcp.tool()
async def refresh_index() -> str:
    """刷新向量索引。当 wiki 页面被外部修改后调用。"""
    ...

def main():
    mcp.run(transport="stdio")
```

7 个 MCP tools:

| Tool | 类型 | 用途 | 频率 |
|------|------|------|------|
| `search_knowledge` | 查询 | 两阶段语义搜索 | 高 |
| `list_notes` | 查询 | 浏览笔记/页面 | 中 |
| `read_note` | 查询 | 读全文 | 中 |
| `ingest_source` | 维护 | 摄入新源 → 更新 wiki | 中 |
| `save_as_page` | 维护 | 好回答存为 wiki 页 | 中 |
| `lint_wiki` | 维护 | 健康检查 | 低 |
| `refresh_index` | 维护 | 刷新向量索引 | 低 |

### 7.7 配置 (config.py)

```python
@dataclass
class Config:
    # Obsidian vault 路径
    vault_path: Path

    # 向量库持久化目录
    chroma_dir: Path

    # Embedding 配置
    embedding_backend: str = "openai"    # openai / local
    openai_api_key: str = ""
    openai_base_url: str = ""            # 可选中转
    embedding_model: str = "text-embedding-3-small"

    # LLM 配置（用于 ingest/lint/save 操作）
    llm_backend: str = "openai"          # openai / anthropic
    llm_model: str = "gpt-4o"
    llm_api_key: str = ""

    # 切分配置
    max_chunk_tokens: int = 1000
    min_chunk_tokens: int = 50

    # 搜索配置
    default_top_k: int = 5
```

环境变量:

```bash
# Vault
KNOWLEDGE_VAULT_PATH=/Users/syf/work/git-hub/fuck/fuck-ai

# 向量库
KNOWLEDGE_CHROMA_DIR=~/.knowledge-mcp/chroma

# Embedding
KNOWLEDGE_EMBEDDING_BACKEND=openai
OPENAI_API_KEY=sk-xxx
OPENAI_BASE_URL=                        # 可选中转

# LLM（用于 ingest/lint 操作）
KNOWLEDGE_LLM_BACKEND=openai
KNOWLEDGE_LLM_MODEL=gpt-4o
```

---

## 八、schema.md — Wiki 规则

这个文件告诉 LLM "怎么维护 wiki"，相当于 AutoAgent 的 program.md：

```markdown
# Knowledge Wiki Schema

## 页面分类
- concepts/    概念页（一个概念一个页面: Agent Loop, MCP, Embedding...）
- entities/    实体页（具体项目/工具/人物: AutoAgent, Code Review Agent...）
- comparisons/ 对比页（两个或多个实体的对比）
- synthesis/   综合分析页（跨多个源的综合结论）

## 页面格式
每个 wiki 页面必须有 YAML frontmatter:
  - title: 页面标题
  - tags: 标签列表
  - sources: 引用的原始源文件列表
  - related: 相关 wiki 页面列表
  - created: 创建日期
  - updated: 最后更新日期
  - status: seedling / developing / mature

## 交叉引用
- 使用 Obsidian [[双链]] 语法引用其他 wiki 页面
- 每个页面至少链接 2 个相关页面（避免孤立）
- 引用原始源时标注 [source: raw/xxx.md]

## Ingest 规则
- 每次摄入后必须更新 index.md
- 每次摄入后必须追加 log.md
- 如果新信息和已有页面矛盾，在页面中用 > [!warning] 标注
- 不要删除已有信息，只追加或标注过时

## 命名约定
- 文件名用小写 + 连字符: agent-loop.md, not AgentLoop.md
- 概念页标题用名词短语: "Agent Loop", not "What is Agent Loop"
- 实体页标题用项目名: "AutoAgent", "Code Review Agent"
```

---

## 九、Obsidian 配合

### Vault 目录结构

```
fuck-ai/                          ← Obsidian Vault 根目录
├── raw/                          ← Layer 1: 原始素材（你写/剪藏）
│   ├── analysis/                 ← 项目分析
│   │   ├── autoagent-analysis.md
│   │   └── code-review-agent-analysis.md
│   ├── notes/                    ← 手写笔记
│   │   └── harness-engineering.md
│   └── articles/                 ← 剪藏文章
├── wiki/                         ← Layer 2: LLM 维护的 wiki
│   ├── concepts/
│   ├── entities/
│   ├── comparisons/
│   └── synthesis/
├── index.md                      ← 目录
├── log.md                        ← 时间线
├── schema.md                     ← Layer 3: Wiki 规则
├── ai-knowledge-base/            ← MCP Server 代码
├── code-review-agent/            ← 另一个项目
├── data_dify/
└── mcp/
```

### 迁移现有文件

你已有的分析文档迁移到 raw/：

```
harness-engineering.md          → raw/notes/harness-engineering.md
autoagent-analysis.md           → raw/analysis/autoagent-analysis.md
code-review-agent-analysis.md   → raw/analysis/code-review-agent-analysis.md
```

然后用 `ingest_source` 逐个摄入，LLM 会自动生成 wiki 页面。

### 推荐 Obsidian 插件

| 插件 | 用途 |
|------|------|
| **Obsidian Git** | 自动 commit/push |
| **Obsidian Web Clipper** | 浏览器剪藏文章为 Markdown |
| **Dataview** | 结构化查询（按 frontmatter 字段） |
| **Templater** | 笔记模板 |
| **Tag Wrangler** | 标签管理 |

### 笔记规范

```markdown
---
tags: [harness-engineering, agent, rust]
date: 2026-04-14
source: https://github.com/xxx
status: seedling
---

# 标题

## 一级主题
内容...

## 二级主题
内容...
```

---

## 十、MCP 客户端配置

```json
{
  "mcpServers": {
    "knowledge": {
      "command": "uv",
      "args": ["--directory", "/Users/syf/work/git-hub/fuck/fuck-ai/ai-knowledge-base", "run", "knowledge_mcp/server.py"],
      "env": {
        "KNOWLEDGE_VAULT_PATH": "/Users/syf/work/git-hub/fuck/fuck-ai",
        "OPENAI_API_KEY": "sk-xxx",
        "KNOWLEDGE_LLM_MODEL": "gpt-4o"
      }
    }
  }
}
```

使用示例：

```
"摄入 raw/analysis/autoagent-analysis.md"
→ 调 ingest_source
→ 创建 wiki/entities/autoagent.md, 更新 wiki/concepts/agent-loop.md, ...
→ 更新 index.md, 追加 log.md

"搜一下 Agent Loop 的设计模式"
→ 调 search_knowledge
→ 先读 index.md 定位，再向量精搜
→ 返回 wiki 中的相关段落

"这个回答很好，存一下"
→ 调 save_as_page
→ 存为 wiki/synthesis/agent-loop-patterns.md

"wiki 健康检查"
→ 调 lint_wiki
→ 返回: 3 个孤立页, 1 个矛盾, 2 个缺失概念页
```

---

## 十一、mkdocs-material — Wiki 静态站点

### 为什么用 mkdocs-material

| 对比 | Obsidian | mkdocs-material |
|------|---------|-----------------|
| 定位 | 个人编辑器（本地） | 发布和分享（静态站点） |
| 访问 | 只有你能看 | 浏览器打开，任何人能看 |
| 搜索 | Obsidian 内置搜索 | 内置全文搜索（lunr.js / 中文支持） |
| 导航 | 文件树 / 图谱 | 侧边栏目录 + 面包屑 + 标签页 |
| 适合 | 写和编辑 | 浏览和分享 |

两者不冲突：**Obsidian 写，mkdocs-material 发布**。同一套 Markdown 文件。

### mkdocs.yml 配置

```yaml
site_name: AI Knowledge Base
site_url: https://yourusername.github.io/fuck-ai/
docs_dir: ../  # 指向 vault 根目录（fuck-ai/）

theme:
  name: material
  language: zh
  palette:
    - scheme: default
      primary: indigo
      toggle:
        icon: material/brightness-7
        name: 切换到暗色模式
    - scheme: slate
      primary: indigo
      toggle:
        icon: material/brightness-4
        name: 切换到亮色模式
  features:
    - navigation.tabs           # 顶部标签页
    - navigation.sections       # 侧边栏分组
    - navigation.expand         # 自动展开
    - navigation.top            # 回到顶部
    - search.suggest            # 搜索建议
    - search.highlight          # 搜索高亮
    - content.code.copy         # 代码复制按钮
    - content.tabs.link         # 标签页联动

plugins:
  - search:
      lang:
        - zh
        - en
  - tags                        # 标签系统

markdown_extensions:
  - pymdownx.highlight          # 代码高亮
  - pymdownx.superfences        # 代码块增强
  - pymdownx.tabbed:            # 标签页
      alternate_style: true
  - pymdownx.tasklist:          # 任务列表
      custom_checkbox: true
  - admonition                  # 提示框（!!! note, !!! warning）
  - attr_list                   # 属性列表
  - def_list                    # 定义列表
  - tables                      # 表格

nav:
  - 首页: index.md
  - AI 调研:
    - Harness Engineering: AI调研/harness-engineering.md
    - AutoAgent 分析: AI调研/autoagent-analysis.md
    - Code Review Agent 分析: AI调研/code-review-agent-analysis.md
    - Karpathy LLM Wiki: karpathy-llm-wiki-analysis.md
  - Wiki:
    - 概念: wiki/concepts/
    - 实体: wiki/entities/
    - 对比: wiki/comparisons/
    - 综合: wiki/synthesis/
  - 项目:
    - Code Review Agent: code-review-agent/DESIGN.md
    - AI 知识库: ai-knowledge-base/DESIGN.md
```

### 使用方式

```bash
# 本地预览
cd ai-knowledge-base
mkdocs serve
# → 浏览器打开 http://127.0.0.1:8000

# 构建静态站点
mkdocs build
# → 输出到 site/ 目录

# 发布到 GitHub Pages
mkdocs gh-deploy
# → 自动推送到 gh-pages 分支
```

### 与 Obsidian 的共存

```
fuck-ai/                     ← Obsidian Vault（写和编辑）
├── .obsidian/                ← Obsidian 配置（mkdocs 忽略）
├── ai-knowledge-base/
│   ├── mkdocs.yml            ← mkdocs 配置
│   └── site/                 ← mkdocs 构建输出（.gitignore）
├── wiki/                     ← 两者共用
├── raw/
└── *.md
```

Obsidian 和 mkdocs-material 读同一套 .md 文件，互不干扰。

---

## 十二、可插拔 Skill 系统

### 核心理念

**Skill 的核心是 Markdown，不是 Python。**

每个 Skill 包的灵魂是 `skill.md` — 它定义了：
- Skill 是什么、能做什么
- LLM 应该怎么使用它（prompt）
- 可用的工具链和优先级
- 参数定义
- 输出格式和 wiki 模板

Python 代码（`executor.py`）只是**薄执行层** — 读 skill.md 的配置，调具体工具，返回结果。
逻辑在 Markdown 里，代码只是胶水。

这和 Code Review Agent 的 Skill 设计一致：Skill = system prompt + 执行入口。
也和 AutoAgent 的 program.md 一致：人写规则，代码执行。

### skill.md 格式规范

每个 Skill 包必须有一个 `skill.md`，结构如下：

```markdown
---
name: video
version: 0.1.0
description: 下载和解析视频（抖音、B站、YouTube），提取信息并生成 wiki 页面
author: syf
tools:                          # 注册为哪些 MCP tools
  - video_download
  - video_info
  - video_direct_link
  - video_to_wiki
requires:                       # 系统依赖
  - yt-dlp
---

# Video Skill

## 能力
- 下载视频（无水印）
- 提取视频直链
- 解析视频信息（标题、作者、时长、标签）
- 提取字幕/转文字
- 生成 wiki 页面（视频摘要）

## 支持平台

| 平台 | 工具 | 方式 | 优先级 |
|------|------|------|--------|
| 抖音 | tikwm API | HTTP API，无水印 | 1 |
| 抖音 | yt-dlp | 命令行 | 2（fallback） |
| B站 | yt-dlp | 命令行 | 1 |
| YouTube | yt-dlp | 命令行 | 1 |
| TikTok | tikwm API | HTTP API | 1 |
| 通用 | gallery-dl | 提取直链 | fallback |

## 工具定义

### video_download
下载视频到本地。
- 参数: url (str, 必填), no_watermark (bool, 默认 true)
- 输出: 下载文件路径 + 视频元信息

### video_info
解析视频信息，不下载。
- 参数: url (str, 必填)
- 输出: JSON 格式的视频元信息（标题、作者、时长、标签、播放量）

### video_direct_link
提取视频无水印直链。
- 参数: url (str, 必填)
- 输出: 可直接下载的视频 URL

### video_to_wiki
完整流程: 下载 → 解析 → 生成 wiki 页面。
- 参数: url (str, 必填)
- 输出: 生成的 wiki 页面路径

## 执行策略

级联尝试，按优先级：
1. 先试平台专属 API（tikwm 等），速度快
2. fallback 到 yt-dlp，兼容性最好
3. 最后试 gallery-dl，提取直链

## Wiki 输出模板

生成的 wiki 页面格式：

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
    - **播放量**: {view_count}

    ## 摘要
    {description}

    ## 标签
    {tags}
```

### Skill 加载机制

Python 代码做的事非常少 — 扫描、加载、执行：

```python
# skills/__init__.py

def discover_skills(skills_dir: Path) -> list[SkillDef]:
    """扫描 skills/ 下所有子目录，找到 skill.md → 解析 frontmatter → 注册。"""
    skills = []
    for skill_dir in skills_dir.iterdir():
        if skill_dir.is_dir():
            skill_md = skill_dir / "skill.md"
            if skill_md.exists():
                meta = parse_frontmatter(skill_md)
                skills.append(SkillDef(
                    name=meta["name"],
                    description=meta["description"],
                    tools=meta.get("tools", []),
                    requires=meta.get("requires", []),
                    skill_dir=skill_dir,
                    prompt=skill_md.read_text(),
                ))
    return skills

@dataclass
class SkillDef:
    name: str
    description: str
    tools: list[str]
    requires: list[str]
    skill_dir: Path
    prompt: str             # skill.md 的完整内容，可以喂给 LLM
```

### 薄执行层 (executor.py)

每个 Skill 包的 `executor.py` 只负责"手脏活" — 调 API、跑命令：

```python
# skills/video/executor.py

class VideoExecutor:
    """视频 Skill 的执行层。逻辑在 skill.md 里，这里只管调工具。"""

    async def download(self, url: str, no_watermark: bool = True) -> dict:
        platform = self._detect_platform(url)
        # 级联尝试（策略在 skill.md 里定义，这里执行）
        for backend in self._get_backends(platform):
            result = await backend(url)
            if result:
                return result
        raise SkillError(f"所有下载后端均失败: {url}")

    async def info(self, url: str) -> dict:
        """只取元信息，不下载。"""
        ...

    async def direct_link(self, url: str) -> str:
        """提取直链。"""
        ...

    # --- 具体后端 ---

    async def _tikwm(self, url: str) -> dict | None:
        """tikwm API — 抖音/TikTok。"""
        resp = await self.client.get("https://www.tikwm.com/api/", params={"url": url})
        ...

    async def _ytdlp(self, url: str) -> dict | None:
        """yt-dlp — 万能后端。"""
        proc = await asyncio.create_subprocess_exec("yt-dlp", "--write-info-json", ...)
        ...

    async def _gallery_dl(self, url: str) -> dict | None:
        """gallery-dl — 直链提取。"""
        ...

    def _detect_platform(self, url: str) -> str:
        if "douyin.com" in url: return "douyin"
        if "bilibili.com" in url or "b23.tv" in url: return "bilibili"
        if "youtube.com" in url or "youtu.be" in url: return "youtube"
        if "tiktok.com" in url: return "tiktok"
        return "unknown"
```

### Skill → MCP Tool 自动注册

server.py 启动时，扫描所有 skill.md → 动态注册 MCP tools：

```python
# server.py

from skills import discover_skills

def register_skill_tools(mcp, skills_dir: Path):
    """读 skill.md → 为每个 tool 动态注册 MCP tool。"""
    for skill in discover_skills(skills_dir):
        executor_module = importlib.import_module(f"skills.{skill.name}.executor")
        executor = executor_module.get_executor()

        for tool_name in skill.tools:
            handler = getattr(executor, tool_name.replace(f"{skill.name}_", ""))
            # 动态注册: skill.md 里定义的 tool name → executor 里的方法
            mcp.tool(name=tool_name, description=f"[{skill.name}] ...")(handler)

# 启动时
register_skill_tools(mcp, Path("skills/"))
```

### 新增 Skill 的流程

要加一个新 Skill（比如 web_clip），只需：

```
1. 创建 skills/web_clip/ 目录
2. 写 skills/web_clip/skill.md（定义能力、工具、prompt、模板）
3. 写 skills/web_clip/executor.py（调 readability / trafilatura 等）
4. 重启 MCP Server → 自动发现并注册
```

不需要改 server.py，不需要改注册代码。**加目录 + 写 md + 写薄执行层 = 新 Skill**。

---

## 十三、实现顺序（更新）

```
Phase 1: 基础（纯文本处理，无 LLM 依赖）
  ① config.py       — 配置加载
  ② chunker.py      — Markdown 切分
  ③ tests/          — 用现有 .md 测试切分效果

Phase 2: 存储 + 检索
  ④ embedder.py     — Embedding 抽象 + OpenAI 实现
  ⑤ store.py        — ChromaDB 封装
  ⑥ indexer.py      — 扫描 → 切分 → embedding → 存储

Phase 3: MCP Server（基础版，纯检索）
  ⑦ server.py       — search_knowledge + list_notes + read_note + refresh_index
  ⑧ 注册到 Claude Code，端到端测试

Phase 4: 知识维护（LLM Wiki 核心）
  ⑨ schema.md       — 编写 wiki 规则
  ⑩ ingester.py     — ingest_source 实现
  ⑪ save_as_page    — 回答回写
  ⑫ lint_wiki       — 健康检查

Phase 5: mkdocs-material 站点
  ⑬ mkdocs.yml      — 配置站点结构、主题、插件
  ⑭ 本地预览        — mkdocs serve 验证
  ⑮ GitHub Pages    — mkdocs gh-deploy 发布

Phase 6: Skill 系统
  ⑯ skills/__init__.py  — Skill 基类 + 注册机制
  ⑰ skills/video.py     — 视频下载/解析（tikwm + yt-dlp）
  ⑱ video MCP tools     — video_download / video_info / video_to_wiki
  ⑲ 测试视频 Skill      — 抖音/B站/YouTube 各测一个

Phase 7: 打磨
  ⑳ 增量更新（只处理变更文件）
  ㉑ 本地 embedding fallback
  ㉒ 两阶段搜索优化（index.md + 向量）
  ㉓ 迁移现有笔记到 raw/，逐个 ingest
  ㉔ 更多 Skill（web_clip, media）
```

---

## 十二、依赖

```toml
[project]
name = "ai-knowledge-base"
version = "0.1.0"
requires-python = ">=3.12"

dependencies = [
    "mcp>=1.25.0",              # MCP SDK (FastMCP)
    "chromadb>=0.5",             # 向量数据库（本地）
    "openai>=1.0",               # OpenAI Embedding + LLM API
    "httpx>=0.27",               # async HTTP
    "pyyaml>=6.0",               # 解析 frontmatter
    "mkdocs-material>=9.5",      # Wiki 静态站点
    "yt-dlp>=2024.0",           # 视频下载（B站、YouTube、抖音 fallback）
]

[dependency-groups]
dev = [
    "pytest>=8.0",
    "pytest-asyncio>=0.24",
]

[project.scripts]
knowledge-mcp = "knowledge_mcp.server:main"
```

注意: `tikwm` API 通过 `httpx` 直接调用，不需要额外依赖。
`gallery-dl` 作为可选 fallback，不列入必须依赖。

---

## 十三、约束

### 做什么
- 三层架构: raw (你写) → wiki (LLM 维护) → schema (规则)
- 通过 MCP 提供检索 + 知识维护 + Skill 调用
- index.md + ChromaDB 双模检索
- ingest 时自动更新交叉引用和标注矛盾
- 好回答可以回写为 wiki 页面
- 定期 lint 保持 wiki 健康
- mkdocs-material 生成静态站点，可发布到 GitHub Pages
- 可插拔 Skill 系统（视频下载/解析、网页剪藏等）

### 不做什么
- 不做笔记编辑（Obsidian 已经很好了）
- 不做自定义 Web UI（mkdocs-material 生成的静态站 + MCP 就够了）
- 不做多用户（个人用）
- 不自动修改 raw/ 下的文件（raw 是 source of truth，不可变）
- Skill 不做视频编辑/转码（只做下载、信息提取、生成 wiki）

---

## 十四、后续演进（不在 v0.1）

- [ ] 支持 Obsidian `[[双链]]` 解析，建立 wiki 页面之间的关联图
- [ ] 搜索时自动带上相关双链笔记作为上下文
- [ ] 本地 embedding（sentence-transformers），离线可用
- [ ] 文件 watcher（fswatch），修改 raw/ 后自动触发 re-ingest
- [ ] 按 tag 过滤搜索（`search_knowledge(query, tags=["agent"])`)
- [ ] 批量 ingest（一次性摄入 raw/ 下所有文件）
- [ ] wiki 页面版本对比（结合 git diff 看 wiki 演进）
- [ ] 多模态: 支持图片描述（LLM 看图后生成文字摘要存入 wiki）
- [ ] Skill: web_clip（网页剪藏为 Markdown）
- [ ] Skill: media（视频字幕提取 → whisper 转文字 → 生成 wiki）
- [ ] Skill: podcast（播客音频 → 转文字 → 生成 wiki）
- [ ] mkdocs-material: GitHub Actions 自动构建部署
- [ ] mkdocs-material: 自定义主题/logo
- [ ] mkdocs-material: 搜索增强（接入 MCP 语义搜索）
