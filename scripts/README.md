# Auto-Improve — AI 自主改进系统

让 AI 24 小时不停分析项目、发现问题、写代码、测试、提交。你只需要 review PR。

## 原理

```
每 30 分钟一轮:

  读取输入（历史/拒绝记录/任务队列/项目知识）
       ↓
  OpenCode Agent 分析 + 改代码
       ↓
  语法检查 + 冒烟测试（失败则回滚）
       ↓
  提交到 dev 分支 + 创建 PR
       ↓
  你 review: merge 或 close
       ↓
  AI 从拒绝中学习，下轮不再犯
```

## 前提

```bash
# 安装 OpenCode
npm install -g opencode-ai

# 安装 GitHub CLI（创建 PR 用）
brew install gh
gh auth login

# 确认 opencode 已配置 LLM provider
opencode
# 输入 /connect 配置
```

## 使用

### 启动

```bash
# 跑一轮
./scripts/auto_improve.sh

# 守护模式（24 小时不停）
./scripts/auto_improve.sh --daemon

# 用 pm2 托管（推荐）
pm2 start scripts/auto_improve.sh --name auto-improve -- --daemon
pm2 logs auto-improve    # 看日志
pm2 stop auto-improve    # 停止
```

### 给 AI 指方向

```bash
# 添加任务（AI 优先做队列里的）
./scripts/auto_improve.sh --add "飞书 Bot 回复加摘要"
./scripts/auto_improve.sh --add "加批量处理功能"

# 拒绝改进（close PR 后执行，告诉 AI 为什么不行）
./scripts/auto_improve.sh --reject "改动破坏了飞书通道"
```

### 查看状态

```bash
# 总览：任务队列 + 最近改进 + 被拒绝记录
./scripts/auto_improve.sh --status

# 完整历史
./scripts/auto_improve.sh --history

# 实时日志
tail -f scripts/.improve.log
```

### Review PR

1. 打开 https://github.com/m17y/akasha/pulls
2. 看 AI 改了什么
3. 好的 → Merge
4. 差的 → Close，然后 `./scripts/auto_improve.sh --reject "原因"`

## 文件说明

```
scripts/
├── auto_improve.sh          # 守护进程主脚本
├── auto_improve.py          # Python 版（备用，直接调 LLM）
├── .improve.log             # 运行日志
├── .improve-history.log     # 改进历史（AI 读取避免重复）
├── .improve-rejected.log    # 被拒绝记录（AI 读取避免再犯）
├── .improve-todo.md         # 任务队列（AI 优先做）
├── .improve-knowledge.md    # 项目知识积累（AI 跨轮学习）
└── README.md                # 本文件
```

## 安全机制

| 机制 | 说明 |
|---|---|
| dev 分支 | 不直接推 main，必须 PR review |
| 语法检查 | 所有 .py 文件，失败回滚 |
| 冒烟测试 | 核心模块导入 + 基本功能，失败回滚 |
| 文件数限制 | 每轮最多改 8 个文件 |
| 超时 | OpenCode 执行上限 10 分钟 |
| 拒绝学习 | close PR 后自动/手动记录，下轮不再犯 |

## AI 的知识积累

`scripts/.improve-knowledge.md` 是 AI 跨轮积累的项目知识：

- 架构要点（哪些文件改动要小心）
- 已知问题（不要重复修）
- 敏感区域（改动前要想清楚）
- 代码规范（async/await、命名、格式）

每轮改进后 AI 会自动更新这个文件。你也可以手动编辑，告诉 AI 额外的规则。
