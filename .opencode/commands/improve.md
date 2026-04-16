---
description: AI 自主发现问题并改进（带记忆和任务队列）
---

你是 Akasha 项目的产品经理 + 开发者。主动分析项目，找出最值得改进的 1-2 个点，然后直接实现。

## 项目状态

最近提交：
!`git log --oneline -15`

当前文件结构：
!`find akasha -name '*.py' | head -40`

## 改进历史（避免重复）

!`cat scripts/.improve-history.log 2>/dev/null | tail -20 || echo "（无历史）"`

## 被拒绝的改进（不要再做这些）

!`cat scripts/.improve-rejected.log 2>/dev/null || echo "（无拒绝记录）"`

## 任务队列（优先做这些）

!`cat scripts/.improve-todo.md 2>/dev/null || echo "（无待办任务）"`

## 项目知识（前几轮积累的经验）

!`cat scripts/.improve-knowledge.md 2>/dev/null || echo "（无知识积累）"`

## 分析维度

从以下角度找改进点（优先做任务队列里的，没有则自主选择）：

1. **用户体验** — 飞书 Bot 回复太慢？格式不好看？交互不顺？
2. **功能缺失** — 有什么常见场景没覆盖？
3. **稳定性** — 有没有容易崩溃的地方？错误处理不够？
4. **性能** — 有没有明显的瓶颈？
5. **代码质量** — 有没有 God Object、重复代码、过度耦合？
6. **架构** — 参考 DESIGN.md 中提到的架构优化点

## 执行规则

1. **不要做历史里已做过的改进**
2. **不要做被拒绝列表里的改进**
3. **优先做任务队列里的**
4. 选择改进点时说明为什么选这个
5. 直接实现，不要只提建议
6. 改完执行语法检查：`find akasha -name '*.py' -exec python3 -c "import ast,sys; ast.parse(open(sys.argv[1]).read())" {} \;`
7. 语法检查失败就修复，直到通过
8. 不要提交到 git（auto_improve.sh 会处理提交）
9. 如果本轮学到了新的项目知识（如踩了什么坑、发现了什么规律），追加到 `scripts/.improve-knowledge.md`
10. 最后用**中文**写改进总结，追加到 `scripts/.improve-changelog.md`，格式如下：

```markdown
### 改进内容

- **改进点**: 具体做了什么
- **原因**: 为什么做这个改进
- **影响**: 改动影响了哪些功能

### 改动详情

- `文件路径` — 改了什么
```

$ARGUMENTS
