# 六层 Agent 架构 — 第30章分析与借鉴

> 来源: https://zhanghandong.github.io/harness-engineering-from-cc-to-ai-coding/part7/ch30.html
> 核心: 从 Claude Code 源码提炼出 22 个命名模式，用 6 层架构组合应用到任意 Agent 项目。
> 这是整本书（前 29 章分析）的实战总结章。

---

## 六层架构全景

```
L6 可观测性  ← 先观察再修复、结构化验证
L5 韧性      ← 有限重试预算、熔断失控循环、局部能力降维
L4 安全      ← 失败关闭、渐进式自主
L3 工具      ← 编辑前先读取、结构化搜索
L2 上下文    ← 为一切设定预算、上下文卫生、告知而非隐藏
L1 提示词    ← 提示词即控制面、带外控制信道
```

每一层解决一个独立的问题，但层与层之间是有依赖的 — 从下往上构建。

---

## 逐层总结

### L1 提示词架构

**核心模式**: 提示词即控制面 + 带外控制信道

**关键设计**: 分离静态部分（宪法/Constitution）和动态部分（运行时/Runtime）

```
System Prompt = Constitution（不变的原则） + Runtime（每次不同的上下文）
```

- Constitution: 审查原则、输出格式、严重级别定义 → 可缓存
- Runtime: 当前文件列表、语言专属规则 → 每次生成

**CC 源码印证**: `DANGEROUS_uncachedSystemPromptSection()` — 任何需要破坏缓存的 prompt 段落，
必须通过这个函数创建并填写原因。通过函数签名而非注释来约束行为。

### L2 上下文管理

**核心模式**: 为一切设定预算 + 告知而非隐藏

**关键设计**: 双层预算（全局 + 单项）+ 截断时注入元信息

```
CC 源码的三层预算:
- DEFAULT_MAX_RESULT_SIZE_CHARS = 50,000    单工具结果
- MAX_TOOL_RESULT_TOKENS = 100,000          单消息聚合
- MAX_TOOL_RESULTS_PER_MESSAGE_CHARS = 200,000  全局上下文
```

**告知而非隐藏**: 截断是不可避免的，但模型必须知道截断发生了。
```
[Truncated: full file has 500 lines, showing first 120]
```
比默默丢弃内容好得多 — 模型知道自己看到的不是全部，就不会基于不完整信息做出错误判断。

**保守估算**: Token 估算用 `bytes / 4`，对非 ASCII 内容会高估，这是有意为之。

### L3 工具与搜索

**核心模式**: 编辑前先读取 + 结构化搜索

**关键设计**: LLM 永远不直接执行工具，它只输出 JSON 请求，代码验证后执行。

```
LLM → 输出 AgentAction JSON → 你的代码验证 → 执行 → 结果返回 LLM
```

**just-bash 洞察**: bash 是 LLM 天然会用的万能工具接口，不需要发明新的工具 DSL。
但必须加沙箱 — 白名单 + 只读。

**Skill ≠ 外部系统**: Skill 就是专项分析的 prompt 模板，由你的代码管理和加载，不需要依赖外部服务。

### L4 安全与权限

**核心模式**: 失败关闭 + 渐进式自主

**关键设计**: 多层防护比单层更可靠（7 层安全约束）

```
1. LLM 不能直接执行操作（纯文本接口）
2. 命令白名单（只允许只读命令）
3. 命令黑名单（显式禁止危险命令）
4. Shell 元字符拦截
5. 输出重定向阻止
6. 调用次数上限（3次/文件）
7. 超时 + 输出截断
```

**渐进式自主**: 不同阶段给不同权限
- Turn 1（审查）: 无工具访问
- Turn 2+（工具）: 只读 bash + skill
- MCP 模式: 外部 Agent 调用，形成嵌套授权

### L5 韧性

**核心模式**: 有限重试预算 + 熔断失控循环

**关键设计**: 没有上限的重试不是韧性 — 是浪费。

CC 源码中的真实数据:
> 在加入熔断器之前，1,279 个会话累计产生了超过 50 次连续失败，
> 每天浪费约 25 万次 API 调用。

```
重试: 指数退避（base_delay * 2^attempt），上限 30 秒
熔断: 连续 N 次失败 → 停止尝试 → 成功后重置
降级: 文件超预算时不放弃，截断后继续审查（局部能力降维）
```

### L6 可观测性

**核心模式**: 先观察再修复 + 结构化验证

**关键设计**: 在写第一行业务逻辑之前，先接入 tracing。

```
review_started（开始时记录配置）
→ file_review_started（每文件记录 token 数）
→ tool_called（工具调用记录）
→ file_review_completed（每文件记录 findings 数）
→ review_completed（汇总：文件数、跳过数、token 消耗、耗时、成本）
```

CC 的类型安全遥测: `LogEventMetadata` 只允许 `boolean | number | undefined`，
从类型层面排除了 `string`，防止意外将代码/文件路径写入日志。

---

## 模式组合 — 比单独理解更重要

模式的价值不在列举，在组合。关键关系：

### 互补关系（一起用效果更好）
- **上下文卫生 + 告知而非隐藏**: 截断内容但保留元信息
- **失败关闭 + 渐进式自主**: 默认锁定 + 按需升级

### 张力关系（需要权衡）
- **为一切设定预算 vs 缓存感知设计**: 截断可能破坏缓存断点
- **编辑前先读取 vs Token 预算**: 读完整文件可能超预算

### 解决张力
为截断行为添加元信息注入，让预算系统在截断时仍保持模型的知情权。

---

## 对我们项目的架构借鉴

### AI 知识库项目 (ai-knowledge-base)

| 层级 | 当前设计 | 可借鉴的优化 |
|------|---------|-------------|
| **L1 提示词** | schema.md 定义 wiki 规则 | 分离 Constitution（不变的知识库原则）和 Runtime（当前 ingest 的文件信息）|
| **L2 上下文** | ChromaDB + index.md 双模检索 | 加 Token 预算（ingest 时限制单文件 token 消耗）+ 截断时注入元信息 |
| **L3 工具** | MCP tools（search/ingest/lint） | Skill 包的 skill.md 就是"工具级提示词" — 已在做 |
| **L4 安全** | 未设计 | 加只读约束（raw/ 不可修改）+ ingest 操作的 wiki 写入验证 |
| **L5 韧性** | 未设计 | 加 LLM 调用重试 + ingest 失败熔断（连续 N 个文件失败 → 停止） |
| **L6 可观测** | 未设计 | 加 tracing: ingest_started/completed, search_query, lint_issues |

### Code Review Agent 项目 (code-review-agent)

已经在 DESIGN.md 中覆盖了大部分，但可以补充：
- L5 韧性层: 当前设计了 retry + circuit breaker，但没有"局部能力降维"
- L6 可观测层: 当前没有明确的 tracing 事件定义

### Skill 系统

第30章的 Skill 设计完全印证了我们 skill.md 为核心的方向：
> "skill 不需要依赖外部系统——它们就是专项分析的提示词模板，由你的 Agent 自己管理和加载。"

skill.md = 工具级提示词（L1）+ 执行策略（L3）的组合体。

---

## 最关键的一句话

> 委托给框架更简单，但你失去了精细控制。自己控制循环意味着每个决策点都是显式的 — 这正是驾驭工程的核心。

这解释了为什么我们选择自己写 Agent Loop 而不是用 LangChain/CrewAI：
**你要驾驭 Agent，不是被框架驾驭。**
