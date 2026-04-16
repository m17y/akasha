---
description: 全面检查项目代码质量
subtask: true
---

对 Akasha 项目进行全面代码检查，找出问题并修复：

## 检查清单

### 1. 语法检查
!`find akasha -name '*.py' -exec python3 -c "import ast,sys; ast.parse(open(sys.argv[1]).read())" {} \; 2>&1 | grep -i error | head -20`

### 2. 导入检查
检查是否有导入不存在的模块（如之前的 SessionManager）。

### 3. 异步一致性
检查 async/await 是否正确，有没有 asyncio.run() 在已有 event loop 中调用的问题。

### 4. 函数签名匹配
检查 executor.py 中注册的 handler 是否和实际函数签名匹配。

如果发现问题，直接修复并提交。
