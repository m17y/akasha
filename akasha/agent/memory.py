"""
Agent 会话记忆 — 按用户存储对话历史。

存储位置: ~/.akasha/sessions/{user_id}.json
每个用户保留最近 N 轮对话，超出自动截断。
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field, asdict
from pathlib import Path


_SESSIONS_DIR = Path.home() / ".akasha" / "sessions"
_MAX_TURNS = 20  # 每个用户最多保留的对话轮次


@dataclass
class Turn:
    """一轮对话（用户 + Agent 回复）。"""

    user: str
    assistant: str
    timestamp: float = field(default_factory=time.time)


@dataclass
class Session:
    """用户会话。"""

    user_id: str
    turns: list[Turn] = field(default_factory=list)

    def add_turn(self, user_msg: str, assistant_msg: str) -> None:
        """添加一轮对话。"""
        self.turns.append(Turn(user=user_msg, assistant=assistant_msg))
        # 截断超出的历史
        if len(self.turns) > _MAX_TURNS:
            self.turns = self.turns[-_MAX_TURNS:]

    def to_messages(self, limit: int = 10) -> list[dict]:
        """把历史对话转为 messages 格式（用于注入 Agent context）。"""
        messages = []
        recent = self.turns[-limit:]
        for turn in recent:
            messages.append({"role": "user", "content": turn.user})
            messages.append({"role": "assistant", "content": turn.assistant})
        return messages

    def save(self) -> None:
        """持久化到文件。"""
        _SESSIONS_DIR.mkdir(parents=True, exist_ok=True)
        path = _SESSIONS_DIR / f"{self.user_id}.json"
        data = {
            "user_id": self.user_id,
            "turns": [asdict(t) for t in self.turns],
        }
        path.write_text(
            json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
        )

    @classmethod
    def load(cls, user_id: str) -> "Session":
        """从文件加载，不存在则返回空会话。"""
        path = _SESSIONS_DIR / f"{user_id}.json"
        if not path.exists():
            return cls(user_id=user_id)
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            turns = [Turn(**t) for t in data.get("turns", [])]
            return cls(user_id=user_id, turns=turns)
        except (json.JSONDecodeError, TypeError, KeyError):
            return cls(user_id=user_id)


class SessionManager:
    """会话管理器 — 缓存 + 持久化。"""

    def __init__(self):
        self._cache: dict[str, Session] = {}

    def get(self, user_id: str) -> Session:
        """获取用户会话（优先内存缓存，其次从文件加载）。"""
        if user_id not in self._cache:
            self._cache[user_id] = Session.load(user_id)
        return self._cache[user_id]

    def record(self, user_id: str, user_msg: str, assistant_msg: str) -> None:
        """记录一轮对话并持久化。"""
        session = self.get(user_id)
        session.add_turn(user_msg, assistant_msg)
        session.save()
