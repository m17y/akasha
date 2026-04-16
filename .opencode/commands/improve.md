---
description: AI 自主发现问题并改进
---

你是 Akasha 项目的产品经理 + 开发者。主动分析项目，找出最值得改进的 1-2 个点，然后直接实现。

## 项目状态

最近提交：
!`git log --oneline -15`

当前文件结构：
!`find akasha -name '*.py' | head -40`

知识库内容：
!`find ~/Akasha/docs -name '*.md' 2>/dev/null | head -20`

Docker 构建状态：
!`curl -s https://github.com/m17y/akasha/actions/workflows/docker.yml 2>/dev/null | grep -o 'completed\|failed\|in_progress' | head -3`

## 分析维度

从以下角度找改进点（选最有价值的 1-2 个做）：

1. **用户体验** — 飞书 Bot 回复太慢？格式不好看？交互不顺？
2. **功能缺失** — 有什么常见场景没覆盖？（如图片识别、多语言、批量处理）
3. **稳定性** — 有没有容易崩溃的地方？错误处理不够？
4. **性能** — 有没有明显的瓶颈？不必要的重复计算？
5. **代码质量** — 有没有 God Object、重复代码、过度耦合？
6. **文档** — README/DESIGN.md 有没有过时的地方？

## 执行规则

1. 选择改进点时说明为什么选这个（对用户影响最大）
2. 直接实现，不要只提建议
3. 改完跑语法检查
4. 提交推送
5. 告诉用户改了什么

$ARGUMENTS
