"""
Agent Executor — 执行单个 action，处理异常。

Agent Loop 决定要做什么（action + params），
Executor 负责实际调用 Vault 的方法并返回结果。
"""

from __future__ import annotations

from typing import Any


class Executor:
    """执行 Agent 的 action，将结果格式化为文本。"""

    def __init__(self, vault):
        """
        Args:
            vault: Vault 实例
        """
        self.vault = vault

        # 核心工具注册表
        self._tools: dict[str, dict] = {
            "search": {
                "handler": self._search,
                "description": "语义搜索笔记",
            },
            "read": {
                "handler": self._read,
                "description": "读取笔记内容",
            },
            "list_notes": {
                "handler": self._list_notes,
                "description": "列出所有已索引文件",
            },
            "refresh_index": {
                "handler": self._refresh_index,
                "description": "刷新索引",
            },
            "ingest": {
                "handler": self._ingest,
                "description": "摄入源文件生成 wiki 页面",
            },
            "save_page": {
                "handler": self._save_page,
                "description": "将内容存为 wiki 页面",
            },
            "lint": {
                "handler": self._lint,
                "description": "Wiki 健康检查",
            },
            "delete_page": {
                "handler": self._delete_page,
                "description": "删除 wiki 页面",
            },
        }

    def get_available_tools(self) -> list[str]:
        """返回所有可用工具名。"""
        tools = list(self._tools.keys())
        # 加上 skill 工具
        if self.vault._skills_loaded:
            tools.extend(self.vault.skill_registry.actions.keys())
        return tools

    async def execute(self, action: str, params: dict[str, Any] | None = None) -> str:
        """执行一个 action。

        Args:
            action: 工具名（如 search、ingest、video_download）
            params: 参数字典

        Returns:
            执行结果文本
        """
        params = params or {}

        try:
            # 优先匹配核心工具
            if action in self._tools:
                handler = self._tools[action]["handler"]
                return await handler(**params)

            # 尝试 skill 工具
            skill_action = self.vault.skill_registry.get_action(action)
            if skill_action is not None:
                return await self.vault.execute_skill(action, **params)

            return (
                f"未知工具: {action}。可用工具: {', '.join(self.get_available_tools())}"
            )

        except Exception as e:
            return f"执行 {action} 失败: {type(e).__name__}: {e}"

    # ── 核心工具实现 ──

    async def _search(self, query: str, top_k: int = 0, tags: str = "") -> str:
        return self.vault.search_formatted(query, top_k=top_k, tags=tags)

    async def _read(self, file_path: str, offset: int = 0) -> str:
        return self.vault.read_formatted(file_path, offset=offset)

    async def _list_notes(self) -> str:
        return self.vault.list_notes_formatted()

    async def _refresh_index(self, force: bool = False) -> str:
        stats = self.vault.refresh_index(force=force)
        return stats.summary()

    async def _ingest(self, source_path: str) -> str:
        return await self.vault.ingest(source_path)

    async def _save_page(
        self, title: str, content: str, category: str = "synthesis"
    ) -> str:
        return await self.vault.save_page(title, content, category)

    async def _lint(self) -> str:
        return self.vault.lint()

    async def _delete_page(self, file_path: str) -> str:
        return self.vault.delete_page(file_path)
