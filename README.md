# Akasha

个人知识库 MCP Server — 语义搜索 + LLM Wiki 知识编译 + 可插拔 Skill 系统。

基于 [Karpathy LLM Wiki](https://gist.github.com/karpathy/1dd0294ef9567971c1e4348a90d69285) 理念：知识不是每次重新检索，而是编译一次、持续更新。

## 30 秒上手

```bash
# 1. 安装（全局命令，任何目录可用）
uv tool install --from /path/to/akasha akasha

# 2. 初始化知识库
akasha init

# 3. 放入你的笔记
cp my-notes.md ~/knowledge-base/docs/raw/notes/

# 4. 查看状态
akasha status
```

完事。现在你的 AI 客户端（OpenCode / Claude Code 等）可以通过 MCP 搜索、摄入、管理你的知识库了。

## 它能做什么

### 基础功能（不需要 LLM，纯本地）

| MCP Tool | 说明 |
|----------|------|
| `search_knowledge` | 语义搜索笔记，支持 tag 过滤 |
| `list_notes` | 列出所有已索引文件 |
| `read_note` | 读取笔记内容（支持分页） |
| `refresh_index` | 刷新索引（增量/全量） |

### 知识维护（需要 LLM API Key）

| MCP Tool | 说明 |
|----------|------|
| `ingest_source` | 摄入源文件 → LLM 提取概念 → 自动创建/更新 wiki 页面 |
| `save_as_page` | 把好回答存为 wiki 页面（知识不消失在聊天记录里） |
| `lint_wiki` | Wiki 健康检查（缺失 frontmatter / 孤立页 / 引用不足） |

### Skill 扩展（可插拔）

| MCP Tool | 说明 |
|----------|------|
| `video_download` | 下载视频到知识库（抖音 / B站 / YouTube） |
| `video_info` | 获取视频信息（标题、作者、时长，不下载） |
| `video_to_wiki` | 下载视频 + 生成带内嵌播放器的 wiki 页面 |

## 安装

### 方式一：全局安装（推荐）

```bash
uv tool install --from /path/to/akasha akasha
```

安装后可以在任何目录直接使用 `akasha` 和 `akasha-site` 命令。

### 方式二：项目内运行

```bash
cd /path/to/akasha
uv sync
uv run akasha help
```

## 配置

所有配置通过环境变量，不设就用默认值：

| 环境变量 | 默认值 | 说明 |
|----------|--------|------|
| `AKASHA_VAULT_PATH` | `~/knowledge-base` | 知识库根目录 |
| `AKASHA_LLM_API_KEY` | (空) | LLM API Key。不设则 ingest/save 不可用，搜索正常 |
| `AKASHA_LLM_BASE_URL` | `https://api.openai.com/v1` | 任何 OpenAI 兼容端点 |
| `AKASHA_LLM_MODEL` | `gpt-4o` | LLM 模型名 |
| `AKASHA_CHROMA_DIR` | `~/.akasha/chroma` | 向量数据库存储目录 |
| `AKASHA_DEFAULT_TOP_K` | `5` | 搜索默认返回条数 |

## 初始化知识库

```bash
akasha init
```

自动创建目录结构：

```
~/knowledge-base/              ← AKASHA_VAULT_PATH
├── mkdocs.yml                 ← 站点配置（动态生成）
├── docs/                      ← 所有 Markdown 内容
│   ├── index.md               ← 知识库目录（自动维护）
│   ├── schema.md              ← wiki 规则（可自定义）
│   ├── log.md                 ← 操作日志（自动追加）
│   ├── raw/                   ← 你的原始素材（LLM 只读，不会被覆盖）
│   │   ├── analysis/          ← 分析文档
│   │   ├── notes/             ← 手写笔记
│   │   └── articles/          ← 剪藏文章
│   ├── wiki/                  ← LLM 维护的 wiki 页面
│   │   ├── concepts/          ← 概念页
│   │   ├── entities/          ← 实体页（项目/工具/视频）
│   │   ├── comparisons/       ← 对比页
│   │   └── synthesis/         ← 综合分析页
│   └── assets/
│       └── video/             ← 下载的视频文件
└── site/                      ← 网站构建产物
```

## 接入 AI 客户端

### OpenCode

在 `~/.config/opencode/opencode.json` 或项目根目录 `opencode.json` 中添加：

```json
{
  "mcp": {
    "akasha": {
      "type": "local",
      "command": ["akasha"],
      "enabled": true,
      "timeout": 30000,
      "environment": {
        "AKASHA_VAULT_PATH": "/Users/你的用户名/knowledge-base",
        "AKASHA_LLM_API_KEY": "sk-xxx",
        "AKASHA_LLM_BASE_URL": "https://api.openai.com/v1",
        "AKASHA_LLM_MODEL": "gpt-4o"
      }
    }
  }
}
```

如果是项目内安装（没有 `uv tool install`），command 改为：

```json
"command": ["uv", "--directory", "/path/to/akasha", "run", "akasha"]
```

### Claude Code / Cursor / 其他 MCP 客户端

同样的配置格式，参考各客户端的 MCP 配置文档。核心就是：
- 命令：`akasha`（或 `uv run akasha`）
- 传输：stdio
- 环境变量：`AKASHA_VAULT_PATH` + 可选的 LLM 配置

重启客户端后生效。

## 使用

### 在 AI 对话中（通过 MCP）

接入后直接用自然语言：

```
搜一下 Agent Loop 设计模式
列出知识库里有哪些笔记
读一下 raw/analysis/autoagent-analysis.md
刷新一下索引
摄入 raw/analysis/autoagent-analysis.md
把这段总结存为 wiki 页面
检查 wiki 健康状态
下载这个视频 https://www.douyin.com/video/xxx
```

### 命令行

```bash
akasha help         # 查看帮助
akasha init         # 初始化知识库目录
akasha status       # 查看配置和索引状态
akasha              # 启动 MCP Server（供 AI 客户端连接，一般不需要手动运行）
```

### 知识库网站

```bash
akasha-site serve   # 本地预览 http://127.0.0.1:8800
akasha-site build   # 构建静态站点到 ~/knowledge-base/site/
akasha-site deploy  # 发布到 GitHub Pages
```

## 工作流示例

### 1. 搜索笔记

```
你: 搜一下 Agent Loop
AI: [调用 search_knowledge] 找到 3 条相关内容...
```

### 2. 摄入文档生成 wiki

```
你: 摄入 raw/analysis/autoagent-analysis.md
AI: [调用 ingest_source]
    摄入完成: raw/analysis/autoagent-analysis.md
      提取概念: Agent Loop, Program.md, 自主 Agent
      创建页面: wiki/entities/autoagent.md, wiki/concepts/agent-loop.md
```

### 3. 下载视频生成 wiki

```
你: 下载这个视频并生成 wiki https://www.douyin.com/video/xxx
AI: [调用 video_to_wiki]
    已生成 wiki 页面: wiki/entities/xxx.md
    （视频已下载到 docs/assets/video/xxx.mp4，页面内嵌播放器）
```

### 4. 保存好回答

```
你: 这个回答总结得很好，存一下
AI: [调用 save_as_page]
    已保存为: wiki/synthesis/agent-design-patterns.md
```

## 项目结构

```
akasha/
├── pyproject.toml
├── akasha/
│   ├── server.py            # MCP Server 入口（10 个 tools + CLI）
│   ├── config.py            # 配置（环境变量 → dataclass）
│   ├── chunker.py           # Markdown 切分（按标题 + frontmatter）
│   ├── store.py             # ChromaDB 向量存储
│   ├── indexer.py           # 索引器（增量更新，基于文件 mtime）
│   ├── llm.py               # LLM 客户端（OpenAI 兼容，自动重试）
│   ├── ingester.py          # 知识摄入器（LLM Wiki 核心）
│   ├── events.py            # 结构化事件日志
│   ├── site.py              # mkdocs-material 站点生成
│   └── skills/
│       ├── __init__.py      # Skill 发现 + 加载（扫描 skill.md）
│       └── video/
│           ├── skill.md     # 视频 Skill 定义（Markdown 是灵魂）
│           └── executor.py  # 执行层（tikwm + yt-dlp 双后端）
└── tests/                   # 117 个测试
```

## 技术栈

| 组件 | 技术 |
|------|------|
| MCP 框架 | `mcp` SDK + `FastMCP` |
| 向量搜索 | ChromaDB（内置 all-MiniLM-L6-v2，本地 embedding，无需 API Key） |
| LLM | OpenAI 兼容 API（自动重试 3 次，120s 超时） |
| 站点 | mkdocs-material（OI-wiki 风格配色） |
| 视频下载 | tikwm API + yt-dlp（级联 fallback） |
| 包管理 | uv + pyproject.toml |
| 语言 | Python 3.12+ |

## 安全

- `raw/` 目录受保护 — LLM 生成的内容只能写入 `wiki/`，不会覆盖你的原始笔记
- 路径穿越防护 — `../` 和目录逃逸会被拦截
- `read_note` 只能读取 docs/ 内的文件

## 添加新 Skill

Skill 的灵魂是 Markdown，Python 只是薄执行层：

```bash
# 1. 创建目录
mkdir akasha/skills/web_clip

# 2. 写 skill.md（定义能力、工具、prompt）
cat > akasha/skills/web_clip/skill.md << 'EOF'
---
name: web_clip
description: 网页剪藏为 Markdown
tools:
  - web_clip_save
---
# Web Clip Skill
...
EOF

# 3. 写 executor.py（调工具的胶水代码）
# 4. 重启 → 自动发现并注册

# 不需要改 server.py，不需要改注册代码
```

## 运行测试

```bash
cd /path/to/akasha
uv run pytest tests/ -v
```
