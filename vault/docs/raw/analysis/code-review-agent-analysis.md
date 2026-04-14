# Code Review Agent 深度分析

> 地址: https://github.com/ZhangHanDong/harness-engineering-from-cc-to-ai-coding/tree/main/examples/code-review-agent
> 来源: 《驾驭工程 — Claude Code 源码分析》配套 Demo
> 语言: Rust | 依赖: cc-sdk, rmcp, tokio, clap, reqwest
> 一句话: 用 Rust 实现的自定义 Agent Loop Code Review 工具，支持 4 种 LLM 后端 + MCP Server 模式。

---

## 这个项目解决什么问题

传统的 AI Code Review 工具（如 GitHub Copilot Review）是黑盒的 — 你不知道它怎么思考、怎么决策、怎么调用工具。

这个项目用 Rust **从零手写** 了一个完整的 Agent Loop，展示了：
- Agent 如何自主决策（继续 / 调工具 / 看关联文件 / 结束）
- 工具系统如何做安全沙箱
- LLM 后端如何做可插拔抽象
- Prompt 如何分层设计（宪法层 + 运行时层）
- 如何同时跑 CLI / MCP Server / Claude Code Skill 三种模式

---

## 项目结构

```
code-review-agent/
├── Cargo.toml          -- 依赖定义
├── Cargo.lock
├── README.md
└── src/
    ├── main.rs         -- CLI 入口 + 后端选择（~140行）
    ├── agent.rs        -- 核心 Agent Loop（~220行）
    ├── llm.rs          -- LlmBackend trait + 4 种实现（~380行）
    ├── tools.rs        -- bash 沙箱 + skill 系统（~320行）
    ├── prompts.rs      -- 系统提示词（宪法 + 运行时 + 跟进提示）（~220行）
    ├── context.rs      -- Diff 解析 + Token 预算管理（~220行）
    ├── review.rs       -- Finding/Report 结构 + AgentAction 枚举（~280行）
    ├── mcp.rs          -- MCP Server（rmcp）（~110行）
    └── resilience.rs   -- 重试 + 熔断器（~130行）
```

总代码量: ~2000 行 Rust，非常精炼。

---

## 架构全景

```
┌──────────────────────────────────────────────────────────────┐
│                        入口层                                 │
│  ┌─────────┐  ┌──────────┐  ┌──────────────────────┐        │
│  │ CLI模式  │  │ MCP模式  │  │ Claude Code Skill模式 │        │
│  │ main.rs  │  │ mcp.rs   │  │  (--serve)           │        │
│  └────┬─────┘  └────┬─────┘  └──────────┬───────────┘        │
│       └──────────────┴──────────────────┘                     │
│                      │                                        │
│                      ▼                                        │
│  ┌───────────────────────────────────────────────────┐       │
│  │              Agent Loop (agent.rs)                 │       │
│  │                                                   │       │
│  │  for each file in diff:                           │       │
│  │    Turn 1: review diff → findings (JSON)          │       │
│  │    Turn 2+: decide next action:                   │       │
│  │      → done (结束)                                │       │
│  │      → review_related { file } (看关联文件)       │       │
│  │      → use_tool { bash, "grep ..." } (跑命令)    │       │
│  │      → use_tool { skill, "security-audit" } (技能) │      │
│  │    max 3 tool calls per file (防跑飞)             │       │
│  │    circuit breaker: 3次连续失败 → 停止            │       │
│  └────────┬─────────────┬────────────────────────────┘       │
│           │             │                                     │
│     ┌─────▼─────┐ ┌────▼────┐                                │
│     │ LLM 后端  │ │ 工具系统 │                                │
│     │ (llm.rs)  │ │(tools.rs)│                                │
│     └───────────┘ └─────────┘                                │
└──────────────────────────────────────────────────────────────┘
```

---

## 核心模块逐一拆解

### 1. Agent Loop (agent.rs) — 最核心

这是整个项目的灵魂，实现了 **think → act → observe** 循环：

```
review_file_with_followup():

  Turn 1: 发 diff 给 LLM → 解析出 findings (JSON 数组)
  
  Turn 2+: (决策循环)
    发 followup_prompt 给 LLM → LLM 返回 AgentAction:
    
    match action:
      Done → 结束，返回 findings
      ReviewRelated { file, reason } → 取关联文件的 diff，再发一次 review
      UseTool { "bash", cmd, reason } → 执行只读 bash → 结果追加到 context → 继续循环
      UseTool { "skill", name, reason } → 用 skill 的 system_prompt 调 LLM → 结果合并到 findings
    
    tool_calls_used >= max_tool_calls(3) → 强制停止
```

关键设计：
- **LLM 不直接执行工具** — LLM 只输出 JSON 指令（`AgentAction`），Rust 代码验证后执行
- **循环有上限** — 每个文件最多 3 次工具调用，防止无限循环
- **熔断保护** — 连续 3 个文件 review 失败，直接跳过剩余文件

### 2. LLM 后端 (llm.rs) — 可插拔设计

```rust
pub trait LlmBackend: Send + Sync {
    fn complete(&self, system: &str, user: &str) 
        -> Pin<Box<dyn Future<Output = Result<LlmResponse>> + Send + '_>>;
}
```

trait 设计极简：**单轮、text-in/text-out**。所有多轮逻辑都在 Agent Loop 里，LLM 只负责文本分析。

4 种实现：

| 后端 | 传输方式 | 认证 | 适用场景 |
|------|---------|------|---------|
| `CcSdkBackend` | 子进程调 claude CLI | CC 订阅 | 默认，本地开发 |
| `CcSdkWsBackend` | WebSocket | Bearer token | 远程 Claude 实例 |
| `CodexBackend` | HTTP SSE | ~/.codex/auth.json | Codex/GPT 订阅 |
| `CodexWsBackend` | WebSocket JSON-RPC | Bearer token | Codex app-server |

**设计亮点**: 用 `&dyn LlmBackend`（动态分发）而不是泛型，理由是 "动态分发的开销相比 LLM 网络延迟可以忽略"。务实。

### 3. 工具系统 (tools.rs) — 安全沙箱

**Bash 工具**（只读沙箱）：

```
安全措施:
├── 命令白名单: cat, grep, find, head, tail, wc, ls, tree, sort, awk...
├── 命令黑名单: rm, mv, cp, curl, wget, python, bash, pip, npm...
├── Shell 元字符拦截: ; | & ` $ ( ) { } 全部禁止
├── 重定向拦截: > 禁止
├── 直接执行: 不用 sh -c，直接 program + args，避免 shell 注入
├── 超时: 30 秒
└── 输出限制: 50KB
```

这个安全模型比很多生产项目都严谨。核心思路是：**bash 是万能工具接口，但必须只读**。

**Skill 工具**（专家分析视角）：

5 个内置 skill，每个都是一套独立的 system prompt：

| Skill | 聚焦领域 |
|-------|---------|
| `security-audit` | 注入、认证、加密、数据泄露、unsafe 代码 |
| `rust-deep` | 所有权、生命周期、并发安全、async 模式、类型设计 |
| `performance-review` | 内存分配、算法复杂度、阻塞、迭代器、动态分发 |
| `api-review` | 公开接口、命名、文档、向后兼容、依赖 |
| `test-coverage` | 覆盖率、边界条件、测试组织、可观测性 |

Skill 的执行方式：加载 skill 的 system prompt → 替换当前 system prompt → 对同一段 diff 重新调 LLM → 合并 findings。

### 4. Prompt 分层 (prompts.rs) — 宪法 + 运行时

```
System Prompt = Constitution (静态) + Runtime (动态)

Constitution（宪法层）:
  - 角色定义: "You are a code review agent"
  - 审查原则: 正确性 > 安全 > 可维护性 > 性能
  - 严重等级定义: Critical / Warning / Info
  - 输出格式: 必须输出 JSON 数组
  - 禁止夸赞: "No false praise"

Runtime（运行时层）:
  - PR 标题 / 文件列表
  - 语言专属规则（自动检测）:
    - .rs → Rust 规则（unwrap、unsafe、clone）
    - .ts/.tsx → TypeScript 规则（any、await、try/catch）
    - .py → Python 规则（bare except、mutable default、type hints）
```

**Followup Prompt** 是另一个精心设计的提示词，给 LLM 提供 4 个选项：
1. `done` — 不需要后续
2. `review_related` — 看关联文件
3. `use_tool { bash, ... }` — 跑只读命令
4. `use_tool { skill, ... }` — 跑专家分析

### 5. Context 管理 (context.rs) — Token 预算

- Token 估算: `bytes / 4`（保守估计，对 CJK 会高估，这是有意为之）
- 全局预算: 默认 50,000 tokens
- 单文件预算: 默认 5,000 tokens
- 超预算处理: 按行截断 + 追加元数据标注 `[Truncated: full file has N lines, showing first M]`
- 预算耗尽: 跳过剩余文件

### 6. MCP Server (mcp.rs) — 一行切换模式

```bash
cargo run -- --serve    # 启动 MCP Server
```

用 `rmcp` crate 实现，暴露一个 `review_diff` tool：
- 输入: diff 文件路径 + 可选 token 预算
- 输出: JSON 格式的 ReviewReport
- MCP 模式固定使用 `CcSdkBackend`（因为跑在 Claude Code 里）

注册到 `.mcp.json` 后，Claude Code 可以直接调这个工具做 Code Review。

### 7. 弹性 (resilience.rs)

- **指数退避重试**: `base_delay * 2^attempt`，上限 30 秒
- **熔断器**: 连续 N 次失败后打开，后续请求直接跳过
- 使用 `AtomicU32` 保证线程安全
- 只在精确的阈值跨越时打日志，避免刷屏

---

## 核心依赖

```toml
cc-sdk = "0.8.1"          # Claude Code SDK（LLM 代理 + WebSocket）
rmcp = "1.3"              # MCP Server 框架（Rust）
tokio = "1.49"            # 异步运行时
tokio-tungstenite = "0.26" # WebSocket 客户端
reqwest = "0.12"          # HTTP 客户端（Codex API）
clap = "4"                # CLI 参数解析
serde / serde_json = "1"  # 序列化
schemars = "1"            # JSON Schema（MCP tool 输入定义）
tracing = "0.1"           # 结构化日志
anyhow = "1"              # 错误处理
```

---

## 设计模式总结

| 模式 | 实现 | 说明 |
|------|------|------|
| **Custom Agent Loop** | agent.rs | 自己控制 think→act→observe，不依赖 LLM 框架的 agent 抽象 |
| **Pluggable Backend** | `dyn LlmBackend` trait | 同一套逻辑，换后端只改一行 `--backend codex` |
| **Tool Sandbox** | bash 白名单 + 元字符拦截 | LLM 请求工具，Rust 代码验证并执行（read-only） |
| **Skill as Tool** | skill system_prompt 替换 | 把 LLM 自身当工具用，换个 prompt 就是一个新"工具" |
| **Constitutional Prompt** | 宪法层 + 运行时层分离 | 静态原则不变，动态上下文按需注入 |
| **Token Budget** | ContextBudget | 全局 + 单文件双层预算，超出截断并标注 |
| **Circuit Breaker** | AtomicU32 计数器 | 连续失败自动熔断，成功重置 |
| **Retry + Backoff** | 指数退避 + 上限 | 处理 LLM API 瞬时故障 |
| **Triple Mode** | CLI / MCP / Skill | 同一个 agent 核心，三种使用方式 |
| **AgentAction Enum** | serde tagged union | LLM 输出 JSON → Rust 类型安全解析 → 分支执行 |

---

## 与 AutoAgent 对比

| 维度 | Code Review Agent | AutoAgent |
|------|-------------------|-----------|
| 定位 | 具体应用（Code Review） | 元框架（Agent 自我优化） |
| 语言 | Rust | Python |
| Agent Loop | 自己写（Rust 控制流） | LLM 框架提供（OpenAI Agents SDK） |
| 工具安全 | 深度沙箱（白名单+黑名单+元字符拦截） | 简单（Docker 隔离） |
| LLM 后端 | 4 种可插拔 | 固定（GPT-5 或 Haiku） |
| 运行模式 | CLI + MCP Server + Skill | Harbor benchmark runner |
| 复杂度 | ~2000 行 Rust | ~400 行 Python |
| Prompt 设计 | 宪法层 + 运行时层 + Skill prompt | 单一 system prompt |
| 核心价值 | 教你怎么**写** Agent | 教你怎么**优化** Agent |

---

## 评价

**优点:**
- **工程质量极高** — 错误处理、日志、测试覆盖、安全防护都非常到位
- **架构极清晰** — 每个文件职责单一，依赖关系一目了然
- **安全模型严谨** — bash 沙箱的多层防护（白名单 + 黑名单 + 元字符 + 无 shell 解释）是教科书级
- **Prompt 设计精巧** — 宪法层 + 运行时层 + 语言自动检测 + Skill 专家视角
- **实用性强** — 不是 toy project，直接能用于实际 Code Review
- **Rust 代码规范** — 大量 `//!` 模块文档、函数文档、`#[cfg(test)]` 测试

**局限:**
- **Rust 门槛高** — 对 Python 开发者不友好，学习曲线陡
- **依赖 cc-sdk** — Claude Code SDK 是较新的 crate，生态还不成熟
- **单文件串行** — 文件之间是顺序 review，没有并发（可能是有意为之，避免 token 竞争）
- **Skill 不可扩展** — 5 个 skill 是硬编码的，没有从文件/配置加载的机制

---

## 可以怎么用

1. **学习 Agent Loop 设计**: 这是目前能找到的最清晰的自定义 Agent Loop 实现，
   比 LangChain/CrewAI 的抽象层清晰得多
2. **抄 bash 沙箱设计**: 如果你要在 MCP Server 里提供 shell 执行能力，
   直接参考这个白名单 + 黑名单 + 元字符拦截的模式
3. **学 Prompt 分层**: 宪法层（不变的原则）+ 运行时层（动态上下文）的分离，
   可以应用到你的 Kyuubi MCP Server 的 prompt 设计
4. **参考 MCP Server 实现**: 用 rmcp crate + `#[tool]` 宏写 MCP Server，
   比你现在用 Python 的 mcp 库写法更类型安全
5. **Skill 即 Prompt 切换**: 这个思路很妙 — 不需要真的写新工具，
   换一套 system prompt 就是一个新"专家"，可以应用到你的 meta MCP Server
