# Akasha

个人 AI 知识库引擎 — 语义搜索 + LLM Wiki 知识编译 + Agent + 可插拔 Skill。

知识不是每次重新检索，而是编译一次、持续更新 — 基于 [Karpathy LLM Wiki](https://gist.github.com/karpathy/1dd0294ef9567971c1e4348a90d69285) 理念。

## 快速开始

```bash
# 安装
uv tool install --from git+https://github.com/m17y/akasha akasha

# 初始化知识库
akasha init

# 配置 LLM（任选一种）
export AKASHA_LLM_API_KEY="sk-xxx"
export AKASHA_LLM_BASE_URL="https://api.openai.com/v1"
export AKASHA_LLM_MODEL="gpt-4o"

# 查看状态（确认配置是否生效）
akasha status

# 启动 Agent
akasha start
```

## 安装与更新

### uv 安装（推荐）

```bash
# 首次安装
uv tool install --from git+https://github.com/m17y/akasha akasha

# 更新到最新版
uv tool install --force --from git+https://github.com/m17y/akasha akasha

# 从本地代码安装（开发用）
uv tool install --force --editable /path/to/akasha

# 卸载
uv tool uninstall akasha

# 清理数据（谨慎）
rm -rf ~/.akasha          # 向量数据库 + 会话记忆
rm -rf ~/akasha           # 知识库内容
```

### Docker 安装

镜像托管在 GitHub Container Registry，每次推送代码自动构建。支持群晖 NAS / 任意 Docker 环境直接拉取。

```bash
# 1. 创建目录并下载配置文件
mkdir akasha && cd akasha
curl -O https://raw.githubusercontent.com/m17y/akasha/main/docker-compose.yml
curl -O https://raw.githubusercontent.com/m17y/akasha/main/.env.example
cp .env.example .env

# 2. 编辑 .env 填入你的配置
vim .env   # 或用任何编辑器

# 3. 启动
docker compose up -d

# 常用命令
docker compose logs -f          # 查看日志
docker compose restart          # 重启
docker compose down             # 停止
docker compose pull && docker compose up -d  # 更新到最新版

# 进入容器执行命令
docker compose exec akasha akasha status
docker compose exec akasha akasha site deploy
```

**群晖 NAS 部署：**

1. Container Manager → 项目 → 新建
2. 上传 `docker-compose.yml` 和 `.env` 文件
3. 启动项目

镜像地址：`ghcr.io/m17y/akasha:latest`

数据持久化在 Docker volume `akasha-data` 中，包含知识库内容和向量数据库。

### pm2 部署（后台常驻）

环境变量统一在 `~/.zshrc`（或 `~/.bashrc`）中配置，ecosystem.config.js 通过 `process.env` 读取，不硬编码敏感信息。

```bash
# 1. 在 ~/.zshrc 中配置环境变量
cat >> ~/.zshrc << 'EOF'

# Akasha 环境变量
export AKASHA_VAULT_PATH="$HOME/akasha"
export AKASHA_LLM_PROVIDER="anthropic"
export AKASHA_LLM_API_KEY="sk-xxx"
export AKASHA_LLM_BASE_URL="https://api.minimaxi.com/anthropic"
export AKASHA_LLM_MODEL="MiniMax-M2.7"
export AKASHA_FEISHU_APP_ID="cli_xxx"
export AKASHA_FEISHU_APP_SECRET="xxx"
export AKASHA_SITE_REPO="https://github.com/user/user.github.io.git"
EOF
source ~/.zshrc

# 2. 创建 ecosystem 配置（从环境变量读取，无需修改）
cat > ~/akasha/ecosystem.config.js << 'EOF'
module.exports = {
  apps: [{
    name: "akasha",
    script: "akasha",
    args: "start",
    interpreter: "none",
    env: {
      AKASHA_VAULT_PATH: process.env.AKASHA_VAULT_PATH,
      AKASHA_LLM_PROVIDER: process.env.AKASHA_LLM_PROVIDER,
      AKASHA_LLM_API_KEY: process.env.AKASHA_LLM_API_KEY,
      AKASHA_LLM_BASE_URL: process.env.AKASHA_LLM_BASE_URL,
      AKASHA_LLM_MODEL: process.env.AKASHA_LLM_MODEL,
      AKASHA_FEISHU_APP_ID: process.env.AKASHA_FEISHU_APP_ID,
      AKASHA_FEISHU_APP_SECRET: process.env.AKASHA_FEISHU_APP_SECRET,
      AKASHA_SITE_REPO: process.env.AKASHA_SITE_REPO,
    },
  }],
};
EOF

# 3. 启动
pm2 start ~/akasha/ecosystem.config.js

# 常用命令
pm2 logs akasha        # 查看日志
pm2 restart akasha     # 重启
pm2 stop akasha        # 停止
pm2 delete akasha      # 删除
pm2 save && pm2 startup  # 开机自启
```

## 命令

```
akasha start           启动 Agent（自动检测并启用已配置的通道）
akasha init            初始化知识库目录结构
akasha status          查看配置和索引状态
akasha mcp             启动 MCP Server (stdio)，供 AI 客户端调用
akasha site serve      知识库网站预览 http://127.0.0.1:8800
akasha site build      构建静态站点
akasha site deploy     发布到 GitHub Pages
```

`akasha start` 会自动检测已配置的通道（飞书等），在后台启用，同时进入交互模式。

## 使用方式

### 交互模式

`akasha start` 默认进入终端交互：

```
akasha> 搜一下 Agent Loop
akasha> /search Agent Loop
akasha> /list
akasha> /status
akasha> /help
```

非命令文本会自动走 Agent 对话（需要 LLM），或作为搜索处理。

### 飞书 Bot

配置好飞书环境变量后，`akasha start` 自动启用飞书通道。在飞书群聊或私聊中 @Bot：

- 发送视频链接（抖音/B站/YouTube）→ 自动下载、转写、分析，生成知识文档
- 发送网页链接 → 自动剪藏保存
- 发送文字 → Agent 对话

也支持命令：

```
/search Agent Loop          搜索知识库
/clip https://example.com   剪藏网页
/video https://douyin.com/xxx 下载视频并生成 wiki
/ingest raw/notes/xxx.md    摄入文档
/status                     查看状态
```

### MCP Server

`akasha mcp` 启动 stdio 模式的 MCP Server，供 AI 客户端（OpenCode / Claude Code / Cursor）调用。

### 知识库网站

`akasha site serve` 启动本地预览，基于知识库内容自动生成 MkDocs Material 站点。

## 配置

所有配置通过环境变量，无需配置文件。

### 核心配置

| 环境变量 | 默认值 | 说明 |
|----------|--------|------|
| `AKASHA_VAULT_PATH` | `~/akasha` | 知识库根目录 |
| `AKASHA_CHROMA_DIR` | `~/.akasha/chroma` | 向量数据库目录 |
| `AKASHA_DEFAULT_TOP_K` | `5` | 搜索默认返回条数 |
| `AKASHA_SITE_REPO` | — (可选) | GitHub Pages 仓库地址，用于 `akasha site deploy` |

### LLM 配置

Akasha 支持两种 LLM Provider，通过 `AKASHA_LLM_PROVIDER` 切换。

| 环境变量 | 默认值 | 说明 |
|----------|--------|------|
| `AKASHA_LLM_PROVIDER` | `openai` | Provider 类型：`openai` 或 `anthropic` |
| `AKASHA_LLM_API_KEY` | — (必填) | API Key |
| `AKASHA_LLM_BASE_URL` | 按 provider 自动设置 | API 端点 |
| `AKASHA_LLM_MODEL` | 按 provider 自动设置 | 模型名称 |

**配置示例：**

```bash
# OpenAI（默认）
export AKASHA_LLM_PROVIDER="openai"
export AKASHA_LLM_API_KEY="sk-xxx"
export AKASHA_LLM_MODEL="gpt-4o"

# MiniMax M2.7（通过 Anthropic API 兼容）
export AKASHA_LLM_PROVIDER="anthropic"
export AKASHA_LLM_API_KEY="sk-xxx"
export AKASHA_LLM_BASE_URL="https://api.minimaxi.com/anthropic"
export AKASHA_LLM_MODEL="MiniMax-M2.7"

# Anthropic Claude
export AKASHA_LLM_PROVIDER="anthropic"
export AKASHA_LLM_API_KEY="sk-ant-xxx"
export AKASHA_LLM_MODEL="claude-sonnet-4-20250514"

# 自部署 / 代理（任何 OpenAI 兼容端点）
export AKASHA_LLM_PROVIDER="openai"
export AKASHA_LLM_API_KEY="sk-xxx"
export AKASHA_LLM_BASE_URL="http://your-server/v1/"
export AKASHA_LLM_MODEL="your-model-name"

# Ollama（本地）
export AKASHA_LLM_PROVIDER="openai"
export AKASHA_LLM_API_KEY="ollama"
export AKASHA_LLM_BASE_URL="http://localhost:11434/v1"
export AKASHA_LLM_MODEL="qwen2.5"
```

### 飞书通道配置

设置以下环境变量后，`akasha start` 会自动启用飞书通道。

| 环境变量 | 说明 |
|----------|------|
| `AKASHA_FEISHU_APP_ID` | 飞书应用 App ID (必填) |
| `AKASHA_FEISHU_APP_SECRET` | 飞书应用 App Secret (必填) |
| `AKASHA_FEISHU_BOT_NAME` | Bot 名称（默认 Akasha） |
| `AKASHA_FEISHU_ENCRYPT_KEY` | 事件加密 Key（可选） |
| `AKASHA_FEISHU_VERIFICATION_TOKEN` | 事件订阅 Verification Token（可选） |

**飞书配置步骤：**

1. [飞书开放平台](https://open.feishu.cn/app) 创建企业自建应用 → 添加 Bot 能力
2. 事件订阅 → 订阅方式选「使用长连接接收事件」
3. 订阅事件：`im.message.receive_v1`
4. 添加权限：`im:message:send_as_bot`、`im:message.receive_v2`
5. 发布应用，复制 App ID 和 App Secret

## 接入 AI 客户端

### OpenCode

```json
{
  "mcp": {
    "akasha": {
      "type": "local",
      "command": ["akasha", "mcp"],
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

配置格式相同，参考各客户端 MCP 文档。核心：命令 `akasha mcp`，传输 stdio。

## 架构

```
┌─────────────────────────────────────┐
│  接入层（薄壳，只做协议转换）         │
│  ├── serve/mcp.py    MCP Server     │
│  ├── serve/cli.py    终端交互        │
│  ├── serve/feishu.py 飞书 Bot        │
│  └── site.py         知识库站点      │
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
│  │   ├── video/      视频下载+分析   │
│  │   ├── web_clip/   网页剪藏        │
│  │   └── media/      音视频转写       │
│  └── llm.py          LLM 客户端      │
└─────────────────────────────────────┘
```

核心设计：**Vault 是唯一入口**。所有接入层都调同一个 Vault 实例，不直接操作底层模块。

## 知识库结构

```
~/akasha/
├── docs/
│   ├── index.md               ← 首页仪表盘（自动生成）
│   ├── schema.md              ← wiki 规则（可自定义）
│   ├── log.md                 ← 操作日志
│   ├── raw/                   ← 原始素材（你写的，LLM 只读）
│   │   ├── analysis/
│   │   ├── notes/
│   │   └── articles/
│   ├── wiki/                  ← LLM 维护的知识页面
│   │   ├── articles/          ← 文章（视频分析、网页剪藏）
│   │   ├── concepts/          ← 概念词条
│   │   ├── entities/          ← 实体记录
│   │   ├── comparisons/       ← 对比分析
│   │   └── synthesis/         ← 综合总结
│   └── assets/video/          ← 下载的视频文件
└── site/                      ← 站点构建产物
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
| LLM | OpenAI + Anthropic 双 Provider（自动重试，120s 超时） |
| MCP | `mcp` SDK + `FastMCP`（stdio） |
| 飞书 | `lark-oapi`（WebSocket 长连接） |
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
uv run pytest tests/ -v
```

## License

MIT
