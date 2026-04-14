# Harness Engineering - GitHub 项目推荐

> Harness Engineering（驾驭工程）：AI Agent 约束、编排与治理的工程化实践。
> 核心思想：通过系统化的约束设计（记忆、权限、上下文、多Agent协调），让 AI Agent 可控、可靠、可生产化。

---

## Top 10 项目

### 1. ModelEngine-Group/nexent (4.3k stars)

- **语言**: Python
- **简介**: 零代码平台，利用 Harness Engineering 原则自动生成生产级 AI Agent，统一工具、技能管理
- **标签**: agent, ai, mcp, multi-agent, harness
- **地址**: https://github.com/ModelEngine-Group/nexent
- **学习价值**: 最火的实战项目，结合了 MCP，适合做 Agent 平台参考

### 2. kevinrgu/autoagent (4.1k stars) -- 深度分析见 [autoagent-analysis.md](./autoagent-analysis.md)

- **语言**: Python
- **简介**: 自治 Harness Engineering（autonomous harness engineering），自动化 Agent 约束与编排
- **地址**: https://github.com/kevinrgu/autoagent
- **学习价值**: 偏研究向，理解自治 Agent 如何自我约束

### 3. walkinglabs/awesome-harness-engineering (1.7k stars)

- **简介**: Harness Engineering 的 Awesome List，汇总了工具、指南、最佳实践
- **地址**: https://github.com/walkinglabs/awesome-harness-engineering
- **学习价值**: 入门首选，先看这个建立全局认知

### 4. deusyu/harness-engineering (1.3k stars)

- **简介**: Harness Engineering 学习指南 -- 从概念理解到独立实践的深度学习档案
- **地址**: https://github.com/deusyu/harness-engineering
- **学习价值**: 中文学习者首选，系统性强

### 5. ZhangHanDong/harness-engineering-from-cc-to-ai-coding (1k stars) -- Code Review Agent 分析见 [code-review-agent-analysis.md](./code-review-agent-analysis.md)

- **语言**: HTML
- **简介**: 从 Claude Code 源码出发理解 Harness Engineering 到 AI Coding 的实践
- **地址**: https://github.com/ZhangHanDong/harness-engineering-from-cc-to-ai-coding
- **学习价值**: 如果你在用 Claude Code / AI 编程工具，这个非常值得看

### 6. walkinglabs/learn-harness-engineering (695 stars)

- **语言**: TypeScript
- **简介**: Harness Engineering 官方风格的入门教程，从 0 到 1
- **地址**: https://github.com/walkinglabs/learn-harness-engineering
- **学习价值**: 动手实践的新手教程

### 7. ai-boost/awesome-harness-engineering (296 stars)

- **语言**: Python
- **简介**: 另一个 Awesome 合集，侧重实用工具
- **地址**: https://github.com/ai-boost/awesome-harness-engineering
- **学习价值**: 补充资源，和 walkinglabs 的 awesome list 互补

### 8. aiming-lab/AutoHarness (223 stars)

- **语言**: Python
- **简介**: 自动化 Harness Engineering for AI Agents，聚焦审计、安全、治理
- **标签**: audit, multi-agent, safety, governance
- **地址**: https://github.com/aiming-lab/AutoHarness
- **学习价值**: 关注 Agent 安全与治理的同学必看

### 9. keli-wen/agentic-harness-patterns-skill (217 stars)

- **简介**: Agent skill for harness engineering -- 记忆、权限、上下文工程、多 Agent 协调，从 Claude Code 中提炼
- **标签**: agent, skills, codex, contexts, gemini-cli
- **地址**: https://github.com/keli-wen/agentic-harness-patterns-skill
- **学习价值**: 直接可用的 Agent Skill 模式，拿来即用

### 10. Picrew/awesome-agent-harness (195 stars)

- **语言**: Python
- **简介**: Agent Harness Engineering 资源合集，含项目、工具、基准测试、实践指南
- **地址**: https://github.com/Picrew/awesome-agent-harness
- **学习价值**: 偏 benchmark 和评测方向

---

## 推荐学习路径

| 阶段 | 项目 | 目标 |
|------|------|------|
| 1. 建立认知 | `walkinglabs/awesome-harness-engineering` | 了解 Harness Engineering 全貌 |
| 2. 系统学习 | `deusyu/harness-engineering` | 中文深度学习档案 |
| 3. 理解原理 | `ZhangHanDong/harness-engineering-from-cc-to-ai-coding` | 从 Claude Code 源码理解本质 |
| 4. 动手入门 | `walkinglabs/learn-harness-engineering` | 从 0 到 1 实践 |
| 5. 实战项目 | `ModelEngine-Group/nexent` | 零代码 Agent 平台，结合 MCP |
| 6. 进阶研究 | `kevinrgu/autoagent` | 自治 Agent 编排 |
| 7. 模式复用 | `keli-wen/agentic-harness-patterns-skill` | 直接可用的 Agent Skill |

---

## 与本仓库的关联

本目录下已有的 MCP 项目（`mcp/kyuubi`、`mcp/meta`）天然与 Harness Engineering 相关：
- MCP Server 本身就是 Harness Engineering 的核心组件之一（工具约束层）
- 可以参考 `nexent` 项目，将现有 MCP Server 纳入统一的 Agent 编排框架
- `agentic-harness-patterns-skill` 中的模式可以直接应用到 MCP Server 的设计中

---

## 相关参考

- [Karpathy LLM Wiki 分析](../karpathy-llm-wiki-analysis.md) — 用 LLM 维护个人知识 wiki 的模式，已融合到 AI 知识库项目设计中
