---
description: 审查最近的改动
subtask: true
---

审查 Akasha 项目最近的代码改动：

## 最近的提交
!`git log --oneline -10`

## 未提交的改动
!`git diff --stat`

## 审查要求
1. 检查是否有遗漏的 bug
2. 检查是否有安全问题（密钥泄漏、路径穿越等）
3. 检查是否有性能问题
4. 检查是否需要更新 README 或 DESIGN.md

只报告有价值的问题，不要提代码风格。
