"""
Memory — Agent 长期记忆。

存储在 docs/memory/ 下，Markdown 格式，持久化。
分两层：
- global.md: 全局记忆（规则、偏好）
- users/{user_id}.md: 用户级记忆
"""

from __future__ import annotations

from datetime import date
from pathlib import Path


class Memory:
    """Agent 长期记忆管理。"""

    def __init__(self, docs_dir: Path):
        self._dir = docs_dir / "memory"
        self._dir.mkdir(parents=True, exist_ok=True)
        (self._dir / "users").mkdir(exist_ok=True)

    # ── 读取 ──

    def get_context(self, user_id: str = "") -> str:
        """获取记忆上下文，注入到 Agent system prompt 中。"""
        parts = []

        # 全局记忆
        global_mem = self._read("global.md")
        if global_mem:
            parts.append(f"## 全局记忆\n\n{global_mem}")

        # 用户记忆
        if user_id:
            user_mem = self._read(f"users/{user_id}.md")
            if user_mem:
                parts.append(f"## 用户记忆\n\n{user_mem}")

        return "\n\n".join(parts)

    # ── 写入 ──

    def remember(self, content: str, user_id: str = "") -> str:
        """记住一条信息。"""
        today = date.today().isoformat()
        entry = f"- {today}: {content}\n"

        if user_id:
            self._append(f"users/{user_id}.md", entry)
        else:
            self._append("global.md", entry)

        return f"已记住: {content}"

    def set_preference(self, key: str, value: str, user_id: str = "") -> str:
        """设置用户偏好（会覆盖同名偏好）。"""
        filepath = f"users/{user_id}.md" if user_id else "global.md"
        full_path = self._dir / filepath

        if full_path.exists():
            text = full_path.read_text(encoding="utf-8")
        else:
            text = f"# 记忆\n\n## 偏好\n\n## 记录\n\n"

        # 查找并替换已有偏好
        lines = text.split("\n")
        new_lines = []
        replaced = False
        for line in lines:
            if line.strip().startswith(f"- {key}:"):
                new_lines.append(f"- {key}: {value}")
                replaced = True
            else:
                new_lines.append(line)

        if not replaced:
            # 在 ## 偏好 后面追加
            for i, line in enumerate(new_lines):
                if line.strip() == "## 偏好":
                    new_lines.insert(i + 2, f"- {key}: {value}")
                    break
            else:
                new_lines.append(f"- {key}: {value}")

        full_path.write_text("\n".join(new_lines), encoding="utf-8")
        return f"已设置偏好: {key} = {value}"

    # ── 内部 ──

    def _read(self, rel_path: str) -> str:
        """读取记忆文件内容。"""
        full_path = self._dir / rel_path
        if not full_path.exists():
            return ""
        text = full_path.read_text(encoding="utf-8")
        # 去掉 frontmatter 和标题
        if text.startswith("# "):
            text = "\n".join(text.split("\n")[1:])
        return text.strip()

    def _append(self, rel_path: str, content: str) -> None:
        """追加内容到记忆文件。"""
        full_path = self._dir / rel_path
        if full_path.exists():
            text = full_path.read_text(encoding="utf-8")
        else:
            text = "# 记忆\n\n## 偏好\n\n## 记录\n\n"

        # 追加到 ## 记录 下面
        if "## 记录" in text:
            text = text.rstrip() + "\n" + content
        else:
            text += f"\n## 记录\n\n{content}"

        full_path.write_text(text, encoding="utf-8")
