# AutoAgent 深度分析 (kevinrgu/autoagent)

> 地址: https://github.com/kevinrgu/autoagent
> 作者: kevinrgu (thirdlayer.inc)
> Stars: 4.1k | Forks: 459 | 语言: Python | License: MIT
> 一句话: 让 AI Agent 自己优化自己的 Agent Harness，像 AutoResearch 一样搞 Agent 工程。

---

## 核心思想

AutoAgent 的哲学是 **"不要手写 harness，让 meta-agent 去写"**：

1. 你有一个 `agent.py`（被测 Agent Harness）
2. 你有一个 `program.md`（给 meta-agent 的指令）
3. Meta-agent（如 Claude Code / Cursor）读 `program.md`，然后反复修改 `agent.py`
4. 每次修改后跑 benchmark，得到分数
5. 分数提升就 keep，否则 discard
6. **无限循环，永不停止，直到人类中断**

这本质上就是 **Agent 工程的爬山算法（Hill Climbing）**。

---

## 项目结构（极简，只有几个文件）

```
autoagent/
├── agent.py              -- 被测 harness（meta-agent 的编辑对象）
├── agent-claude.py       -- Claude 版本的 agent 实现
├── program.md            -- 给 meta-agent 的完整指令（人类编辑这个）
├── pyproject.toml         -- 依赖定义
├── Dockerfile.base        -- Docker 基础镜像
├── progress.png           -- 分数提升曲线图
├── tasks/                 -- benchmark 任务（Harbor 格式）
├── jobs/                  -- 运行输出
├── results.tsv            -- 实验日志
└── .agent/                -- 可选的工作空间
```

---

## 架构分层

```
┌─────────────────────────────────────────────────┐
│  人类                                            │
│  只编辑 program.md（指令/约束/策略）              │
└────────────────────┬────────────────────────────┘
                     │ 读取
┌────────────────────▼────────────────────────────┐
│  Meta-Agent（Claude Code / Cursor / Codex）      │
│  读 program.md → 分析失败 → 修改 agent.py → 跑分 │
│  循环：edit → benchmark → keep/discard → repeat  │
└────────────────────┬────────────────────────────┘
                     │ 编辑
┌────────────────────▼────────────────────────────┐
│  agent.py（被测 Harness）                        │
│  ┌─────────────────────────────────────────────┐│
│  │ EDITABLE SECTION（可编辑区域）               ││
│  │  - SYSTEM_PROMPT    系统提示词               ││
│  │  - MODEL            模型选择                 ││
│  │  - MAX_TURNS        最大轮数                 ││
│  │  - create_tools()   工具定义                 ││
│  │  - create_agent()   Agent 构建               ││
│  │  - run_task()       编排逻辑                 ││
│  └─────────────────────────────────────────────┘│
│  ┌─────────────────────────────────────────────┐│
│  │ FIXED ADAPTER BOUNDARY（禁止修改区域）       ││
│  │  - Harbor 集成                              ││
│  │  - ATIF 轨迹序列化                          ││
│  │  - AutoAgent 适配器类                        ││
│  └─────────────────────────────────────────────┘│
└─────────────────────────────────────────────────┘
                     │ 运行
┌────────────────────▼────────────────────────────┐
│  Harbor Benchmark（Docker 隔离的任务评测）        │
│  tasks/ → 每个任务有 instruction + verifier      │
│  输出: score 0.0~1.0                             │
└─────────────────────────────────────────────────┘
```

---

## 两个 Agent 实现对比

项目提供了两个版本的 agent.py：

| 维度 | agent.py (OpenAI) | agent-claude.py (Claude) |
|------|-------------------|--------------------------|
| SDK | `openai-agents` (OpenAI Agents SDK) | `claude_agent_sdk` (Claude SDK) |
| 默认模型 | `gpt-5` | `haiku` |
| 工具 | 手写 `run_shell` 函数工具 | 使用 `claude_code` preset 预设工具集 |
| 思维链 | 无 | `thinking` 开启，budget 10000 tokens |
| 运行方式 | 宿主机运行，远程 exec | 容器内运行 |
| 复杂度 | ~170 行 | ~240 行 |
| 可编辑面 | prompt/tools/agent/orchestration | prompt/tools/MCP/subagents/hooks |

**关键区别**: Claude 版本暴露了更多调优旋钮（MCP servers、subagents、hooks、thinking budget），
说明 Claude SDK 的 harness 设计自由度更大。

---

## program.md 的设计精髓

`program.md` 是这个项目最值得学习的部分。它不是简单的 prompt，而是一套完整的**元工程规范**：

**1. 角色定义**
```
你是 professional agent harness engineer 和 meta-agent
你的工作不是解决 benchmark 任务，而是改进 harness 让 agent 自己变好
```

**2. 编辑边界**
```
可改: SYSTEM_PROMPT, tools, agent 构建, 编排逻辑
禁改: FIXED ADAPTER BOUNDARY 以下的代码
```

**3. Keep/Discard 规则（严格）**
```
passed 提升 → keep
passed 不变但更简 → keep
其他 → discard
```

**4. 反过拟合规则**
```
测试: "如果这个任务消失了，这个改进还值得吗？"
如果答案是否 → 这是过拟合
```

**5. 失败分析框架**
```
- 任务理解错误
- 缺少能力或工具
- 信息收集不足
- 执行策略错误
- 缺少验证步骤
- 环境/依赖问题
- 静默失败（agent 以为成功但实际输出错误）
```

**6. 自主循环指令（最关键）**
```
NEVER STOP. 不要停下来问要不要继续。
不要在"好的停止点"暂停。
你是自治的，持续循环直到人类中断。
```

---

## 核心依赖

```toml
[project]
requires-python = ">=3.12"
dependencies = [
    "openai-agents",     # OpenAI Agents SDK
    "pandas",            # 数据处理
    "openpyxl",          # Excel 处理
    "numpy",             # 数值计算
    "harbor",            # Agent 评测框架
]
```

- **harbor**: https://github.com/laude-institute/harbor — Agent benchmark 框架，
  提供 Docker 隔离的任务环境、标准化的任务格式、自动评分
- **openai-agents**: OpenAI 官方 Agent SDK，提供 tool/handoff/runner 抽象

---

## 关键设计模式总结

| 模式 | 说明 |
|------|------|
| **Meta-programming** | 人写 program.md，meta-agent 写 agent.py |
| **Hill Climbing** | 每次改一个点，跑分，好就留，差就丢 |
| **Edit Surface** | 明确标注哪些代码可以改，哪些不能改 |
| **Docker Isolation** | 所有任务在容器里跑，不会搞坏宿主机 |
| **ATIF Trajectory** | 标准化的 Agent 轨迹格式，用于复盘分析 |
| **Score-driven** | 一切以分数说话，不靠直觉 |
| **Anti-overfitting** | 明确禁止针对特定任务的 hack |
| **Simplicity Bias** | 同分选更简洁的实现 |
| **Never Stop** | 自主循环，不等人类确认 |

---

## 评价

**优点:**
- 理念极其前沿 — 用 AI 优化 AI 的工程实践，真正的 "autonomous engineering"
- 代码极简 — 整个项目核心就 2 个 Python 文件 + 1 个 Markdown
- program.md 写得极好 — 可以直接当模板用于任何类似的 meta-agent 场景
- 边界设计清晰 — editable vs fixed 的划分是 harness engineering 的精髓

**局限:**
- 只有 2 个 commits，项目还很早期
- tasks/ 目录为空 — 没有自带 benchmark，需要自己加
- 依赖 Harbor 框架 — 这个框架本身也比较新，文档不完善
- 需要强力的 meta-agent（Claude Code / Cursor）— 不是任何 LLM 都能胜任

---

## 可以怎么用

1. **直接复用 program.md 模式**: 把 `program.md` 的结构搬到你自己的 Agent 项目中，
   让 Claude Code 帮你优化 MCP Server 的 prompt/工具设计
2. **学习 Edit Surface 设计**: 在你的 `kyuubi_mcp.py` 中划分可编辑区域和固定区域
3. **引入 benchmark 驱动**: 给你的 MCP Server 写评测任务，用分数驱动迭代
4. **抄 ATIF 轨迹格式**: 标准化你的 Agent 执行日志，方便复盘和调试
