"""
共享 fixtures。
"""

import pytest
from pathlib import Path


@pytest.fixture
def tmp_vault(tmp_path: Path) -> Path:
    """创建一个临时 vault 目录，文件放在 docs/ 下以匹配新架构。

    返回 docs/ 目录路径（给 chunker/store 直接用）。
    Config(vault_path=tmp_vault.parent) 时 docs_dir 会指向这个目录。
    """
    docs = tmp_path / "docs"
    docs.mkdir()

    # 文件 1: 带 frontmatter + 多级标题
    note1 = docs / "bigdata" / "hive.md"
    note1.parent.mkdir(parents=True)
    note1.write_text(
        """\
---
tags:
  - hive
  - sql
title: Hive 笔记
date: 2026-04-14
status: developing
---

# Hive 概述

Hive 是一个基于 Hadoop 的数据仓库工具，可以将结构化数据映射为一张表。

## 窗口函数

ROW_NUMBER, RANK, DENSE_RANK 是常用的窗口函数，用于排名和分组。

## 分区表

分区表通过 PARTITION BY 子句实现，可以加速查询。
""",
        encoding="utf-8",
    )

    # 文件 2: 无 frontmatter
    note2 = docs / "python" / "basics.md"
    note2.parent.mkdir(parents=True)
    note2.write_text(
        """\
# Python 基础

## 列表推导式

列表推导式是 Python 中创建列表的简洁方式，例如 [x**2 for x in range(10)]。

## 字典操作

Python 字典是基于哈希表实现的键值对容器，常用操作包括 get, items, keys, values。
""",
        encoding="utf-8",
    )

    # 文件 3: 内容太短
    note3 = docs / "short.md"
    note3.write_text("# Hi\n\nToo short.", encoding="utf-8")

    # 文件 4: 在 .git 目录下
    git_dir = docs / ".git"
    git_dir.mkdir()
    (git_dir / "notes.md").write_text(
        "# Should be skipped\n\nThis content is in .git and should not be indexed.",
        encoding="utf-8",
    )

    # 文件 5: 无标题
    note5 = docs / "plain.md"
    note5.write_text(
        "这是一段没有任何标题的纯文本内容，用来测试没有标题时是否会作为一个整体 chunk 被索引。这段文字足够长。",
        encoding="utf-8",
    )

    # 文件 6: 带 tags 为字符串格式
    note6 = docs / "agent" / "loop.md"
    note6.parent.mkdir(parents=True)
    note6.write_text(
        """\
---
tags: agent, loop, design-pattern
title: Agent Loop 设计模式
source: https://example.com/agent-loop
---

# Agent Loop

## 核心思想

Agent Loop 是一种设计模式，通过循环执行 Think → Act → Observe 三个步骤来完成复杂任务。

## 实现要点

1. Think: LLM 根据当前状态和历史决定下一步
2. Act: 调用工具执行操作
3. Observe: 观察执行结果，反馈给 LLM
""",
        encoding="utf-8",
    )

    return docs
