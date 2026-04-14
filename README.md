# Akasha

个人 AI 知识库引擎 — 语义搜索 + LLM Wiki 知识编译 + Agent + 可插拔 Skill。

知识不是每次重新检索，而是编译一次、持续更新 — 基于 [Karpathy LLM Wiki](https://gist.github.com/karpathy/1dd0294ef9567971c1e4348a90d69285) 理念。

## 快速开始

```bash
# 安装
uv tool install --from git+https://github.com/m17y/akasha akasha

# 初始化知识库
akasha init

# 放入笔记
cp my-notes.md ~/akasha/docs/raw/notes/

# 查看状态
akasha status
```

## 使用方式

Akasha 有四种接入方式，核心逻辑相同：

| 命令 | 方式 | 适用场景 |
|------|------|----------|
| `akasha` | MCP Server (stdio) | AI 客户端（OpenCode / Claude Code / Cursor） |
| `akasha-cli` | 命令行 | 终端直接使用 |
| `akasha-feishu` | 飞书 Bot (webhook) | 团队协作，在飞书里管理知识库 |
| `akasha-site` | 静态站点 (mkdocs) | 浏览器查看知识库 |

### 命令行 (akasha-cli)

```bash
akasha-cli search "Agent Loop"       # 搜索
akasha-cli list                       # 列出所有笔记
akasha-cli read raw/notes/xxx.md     # 读取笔记
akasha-cli lint                       # Wiki 健康检查
akasha-cli ask "把最近的文章整理一下"   # Agent 模式（需要 LLM）
```

### MCP Server (akasha)

启动后 AI 客户端通过 stdio 调用。支持两种模式：

**Agent 模式（推荐）** — 一个 `ask` tool，用户说意图，Agent 自己规划执行：

```
搜一下 Agent Loop 设计模式
把最近的文章都整理一下
下载这个视频并生成 wiki
```

**细粒度模式（向后兼容）** — 每个功能一个 tool：

| Tool | 说明 |
|------|------|
| `search_knowledge` | 语义搜索，支持 tag 过滤 |
| `list_notes` | 列出已索引文件 |
| `read_note` | 读取笔记内容 |
| `refresh_index` | 刷新索引 |
| `ingest_source` | 摄入源文件生成 wiki 页面 |
| `save_as_page` | 将内容存为 wiki 页面 |
| `lint_wiki` | Wiki 健康检查 |
| `video_download` | 下载视频 |
| `video_info` | 获取视频信息 |
| `video_to_wiki` | 下载视频 + 生成 wiki |
| `web_clip_save` | 剪藏网页 |
| `web_clip_read` | 提取网页正文 |
| `media_transcribe` | 音视频转文字 |
| `media_to_wiki` | 转写 + 生成 wiki |

### 飞书 Bot (akasha-feishu)

在飞书群聊或私聊中管理知识库：

```bash
# 启动（需要先配置飞书凭证）
akasha-feishu
```

飞书中发送命令：

```
/search Agent Loop          搜索知识库
/clip https://example.com   剪藏网页
/video https://douyin.com/xxx 下载视频
/ingest raw/notes/xxx.md    摄入文档
/status                     查看状态
/lint                       健康检查
```

非命令文本自动当作搜索处理。

### 知识库网站 (akasha-site)

```bash
akasha-site serve   # 本地预览 http://127.0.0.1:8800
akasha-site build   # 构建静态站点
akasha-site deploy  # 发布到 GitHub Pages
```

## 安装

```bash
# 从 GitHub（推荐）
uv tool install --from git+https://github.com/m17y/akasha akasha

# 从本地路径
uv tool install --from /path/to/akasha akasha

# 开发模式
cd /path/to/akasha && uv sync && uv run akasha help
```

## 配置

所有配置通过环境变量：

**Akasha 核心**

| 环境变量 | 默认值 | 说明 |
|----------|--------|------|
| `AKASHA_VAULT_PATH` | `~/akasha` | 知识库根目录 |
| `AKASHA_LLM_API_KEY` | — | LLM API Key |
| `AKASHA_LLM_BASE_URL` | `https://api.openai.com/v1` | 任何 OpenAI 兼容端点 |
| `AKASHA_LLM_MODEL` | `gpt-4o` | LLM 模型名 |
| `AKASHA_CHROMA_DIR` | `~/.akasha/chroma` | 向量数据库目录 |
| `AKASHA_DEFAULT_TOP_K` | `5` | 搜索默认返回条数 |

**飞书 Bot（仅 akasha-feishu 使用）**

| 环境变量 | 说明 |
|----------|------|
| `FEISHU_APP_ID` | 飞书应用 App ID |
| `FEISHU_APP_SECRET` | 飞书应用 App Secret |
| `FEISHU_VERIFICATION_TOKEN` | 事件订阅 Verification Token |
| `FEISHU_ENCRYPT_KEY` | 事件加密 Key（可选） |
| `FEISHU_BOT_NAME` | Bot 名称（默认 Akasha） |
| `FEISHU_PORT` | webhook 端口（默认 9000） |

## 接入 AI 客户端

### OpenCode

```json
{
  "mcp": {
    "akasha": {
      "type": "local",
      "command": ["akasha"],
      "enabled": true,
      "timeout": 30000,
      "environment": {
        "AKASHA_VAULT_PATH": "/Users/你的用户名/akasha",
        "AKASHA_LLM_API_KEY": "sk-xxx"
      }
    }
  }
}
```

### Claude Code / Cursor

配置格式相同，参考各客户端 MCP 文档。核心：命令 `akasha`，传输 stdio。

## 架构

```
┌─────────────────────────────────────┐
│  接入层（薄壳，只做协议转换）         │
│  ├── serve/mcp.py    MCP Server     │
│  ├── serve/cli.py    命令行          │
│  ├── serve/feishu.py 飞书 Bot        │
│  └── site.py         静态站点        │
├─────────────────────────────────────┤
│  Agent（大脑）                       │
│  ├── agent/loop.py   决策循环        │
│  ├── agent/executor.py 执行 action   │
│  └── agent/prompts/  system prompt   │
├─────────────────────────────────────┤
│  Vault（核心，唯一入口）              │
│  vault.py → search / read / ingest  │
│             / save_page / lint / ask │
├─────────────────────────────────────┤
│  能力层                              │
│  ├── compiler.py     知识编译        │
│  ├── storage/        文件 + 向量索引  │
│  ├── skills/         可插拔扩展       │
│  │   ├── video/      视频下载        │
│  │   ├── web_clip/   网页剪藏        │
│  │   └── media/      音视频转写       │
│  └── llm.py          LLM 客户端      │
└─────────────────────────────────────┘
```

核心设计：**Vault 是唯一入口**。所有接入层（MCP / CLI / 飞书）都调同一个 Vault 实例，不直接操作底层模块。

## 知识库结构

```
~/akasha/
├── docs/
│   ├── index.md               ← 知识库目录（自动维护）
│   ├── schema.md              ← wiki 规则（可自定义）
│   ├── log.md                 ← 操作日志
│   ├── raw/                   ← 原始素材（LLM 只读）
│   │   ├── analysis/
│   │   ├── notes/
│   │   └── articles/
│   ├── wiki/                  ← LLM 维护的 wiki 页面
│   │   ├── concepts/
│   │   ├── entities/
│   │   ├── comparisons/
│   │   └── synthesis/
│   └── assets/video/
└── site/                      ← 站点构建产物
```

三层知识架构：
- **Raw** — 你的原始笔记，LLM 只读不写
- **Wiki** — LLM 维护的结构化页面
- **Schema** — wiki 组织规则

## 项目结构

```
akasha/
├── vault.py                 # 知识库唯一入口
├── config.py                # 配置
├── compiler.py              # 知识编译（ingest / save / lint）
├── llm.py                   # LLM 客户端
├── site.py                  # mkdocs 站点生成
├── storage/
│   ├── files.py             # 文件读写 + 路径安全
│   └── index.py             # 向量索引
├── agent/
│   ├── loop.py              # Agent Loop
│   ├── executor.py          # 执行 action
│   └── prompts/system.md    # Agent prompt
├── skills/
│   ├── video/               # 视频（tikwm + yt-dlp）
│   ├── web_clip/            # 网页剪藏
│   └── media/               # 音视频转写（whisper）
└── serve/
    ├── mcp.py               # MCP Server
    ├── cli.py               # 命令行
    └── feishu.py            # 飞书 Bot
```

## 添加新 Skill

Skill 的灵魂是 Markdown，Python 只是薄执行层。添加新 Skill 不需要改任何现有代码，重启即自动发现。

```
akasha/skills/your_skill/
├── skill.md        ← 定义名称、描述、工具列表 + Agent 能力说明
└── executor.py     ← 执行逻辑，提供 get_executor() 函数
```

skill.md 同时是 Agent 的能力说明书 — Agent 启动时读取所有 skill.md，理解自己有什么扩展能力。

## 技术栈

| 组件 | 技术 |
|------|------|
| 核心 | Python 3.12+ / uv |
| 向量搜索 | ChromaDB（内置 all-MiniLM-L6-v2，本地 embedding） |
| LLM | OpenAI 兼容 API（自动重试，120s 超时） |
| MCP | `mcp` SDK + `FastMCP`（stdio） |
| 飞书 | `lark-oapi` + Starlette + Uvicorn |
| 站点 | mkdocs-material |
| 视频 | tikwm API + yt-dlp |
| 剪藏 | 内置 HTML 解析器 |
| 转写 | ffmpeg + whisper |

## 安全

- **raw/ 写保护** — LLM 只能写入 wiki/
- **路径穿越防护** — `../` 和目录逃逸被拦截
- **读取限制** — 只能访问 docs/ 内的文件

## 运行测试

```bash
uv run pytest tests/ -v    # 119 个测试
```

## License

MIT
