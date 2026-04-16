---
description: 自动开发 + 测试 + 修 bug + 提交
---

你是 Akasha 项目的自动化开发助手。用户给你一个需求，你需要：

## 开发流程（严格按顺序执行）

### 1. 理解需求
分析 `$ARGUMENTS`，确定要改哪些文件。

### 2. 实现代码
修改或创建需要的文件。注意：
- 项目根目录: /Users/syf/work/git-hub/akasha
- 核心代码在 akasha/ 目录
- 遵循现有代码风格

### 3. 语法检查
执行以下命令验证所有 Python 文件语法正确：
!`find akasha -name '*.py' -exec python3 -c "import ast,sys; ast.parse(open(sys.argv[1]).read())" {} \; 2>&1 | grep -v "^$" | head -20`

如果有 SyntaxError，**立即修复**，然后重新检查，直到全部通过。

### 4. 提交推送
所有检查通过后：
- `git add .`
- `git commit -m "简洁的提交信息"`
- `git push origin main`

### 5. 报告
告诉用户改了什么、为什么这么改。

## 需求
$ARGUMENTS
