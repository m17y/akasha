"""
结构化事件日志 — L6 可观测性。

所有关键操作通过 emit() 记录事件，格式统一:
  [akasha] {event} key=value key=value ...

用途:
- 调试: 知道哪个操作在什么时候做了什么
- 监控: grep 日志即可统计搜索量、ingest 成功率等
- 排查: 失败时有完整上下文
"""

from __future__ import annotations

import sys
import time
from typing import Any


def emit(event: str, **kwargs: Any) -> None:
    """输出一条结构化事件日志。

    Args:
        event: 事件名称（如 search_query, ingest_started, index_built）
        **kwargs: 键值对上下文
    """
    parts = [f"[akasha] {event}"]
    for k, v in kwargs.items():
        if isinstance(v, float):
            parts.append(f"{k}={v:.2f}")
        elif isinstance(v, str) and len(v) > 80:
            parts.append(f'{k}="{v[:80]}..."')
        else:
            parts.append(f"{k}={v}")
    print(" ".join(parts), file=sys.stderr)


class Timer:
    """计时上下文管理器，用于测量操作耗时。"""

    def __init__(self):
        self.start: float = 0
        self.elapsed: float = 0

    def __enter__(self):
        self.start = time.time()
        return self

    def __exit__(self, *_):
        self.elapsed = time.time() - self.start


# ── 预定义事件名 ──

# 搜索
SEARCH_QUERY = "search_query"
SEARCH_RESULT = "search_result"

# 索引
INDEX_STARTED = "index_started"
INDEX_COMPLETED = "index_completed"

# 知识摄入
INGEST_STARTED = "ingest_started"
INGEST_COMPLETED = "ingest_completed"
INGEST_FAILED = "ingest_failed"

# Wiki
SAVE_PAGE = "save_page"
LINT_COMPLETED = "lint_completed"

# Skill
SKILL_LOADED = "skill_loaded"
SKILL_EXEC = "skill_exec"
SKILL_FAILED = "skill_failed"

# 安全
SECURITY_BLOCKED = "security_blocked"
