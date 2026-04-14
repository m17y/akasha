"""
Agent Loop — observe → think → act 循环。

用户说一句话 → Agent 通过多轮 LLM 调用理解意图、规划执行、观察结果，
直到任务完成。
"""

from __future__ import annotations

import json
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from .executor import Executor


# ---------------------------------------------------------------------------
# 数据结构
# ---------------------------------------------------------------------------


@dataclass
class AgentMessage:
    """Agent 对话中的一条消息。"""

    role: str  # system / user / assistant / tool_result
    content: str


@dataclass
class AgentStep:
    """Agent 执行的一步。"""

    thought: str  # Agent 的思考
    action: str | None = None  # 调用的工具名
    params: dict[str, Any] | None = None  # 工具参数
    result: str | None = None  # 工具返回结果


# ---------------------------------------------------------------------------
# Agent Loop
# ---------------------------------------------------------------------------


MAX_STEPS = 20  # 最大执行步数，防止无限循环
_WARN_AT_STEP = 15  # 接近上限时提醒 Agent 收尾


class AgentLoop:
    """Agent 决策循环。

    用法:
        vault = Vault("~/akasha")
        agent = AgentLoop(vault)
        response = await agent.run("把最近的文章都整理一下")
    """

    def __init__(
        self, vault, llm_client=None, on_step: Callable[[str], None] | None = None
    ):
        """
        Args:
            vault: Vault 实例
            llm_client: LLMClient 实例。None 则从 vault.config 创建。
            on_step: 每步执行时的回调，用于实时输出进度。
        """
        self.vault = vault
        self.executor = Executor(vault)
        self.on_step = on_step or (lambda msg: None)

        if llm_client is not None:
            self.llm = llm_client
        else:
            from ..llm import create_llm_client

            self.llm = create_llm_client(vault.config)

        self._system_prompt = self._build_system_prompt()
        self.steps: list[AgentStep] = []

    def _build_system_prompt(self) -> str:
        """拼装 system prompt = system.md + 运行时信息 + skill prompts。"""
        prompts_dir = Path(__file__).parent / "prompts"

        # 读取 system.md
        system_md = prompts_dir / "system.md"
        parts = []
        if system_md.exists():
            parts.append(system_md.read_text(encoding="utf-8"))

        # 注入运行时信息（模型、知识库状态等）
        cfg = self.vault.config
        runtime_info = (
            f"\n## 运行时信息\n\n"
            f"- 底层模型: {cfg.llm_model_resolved} (provider: {cfg.llm_provider})\n"
            f"- 知识库路径: {cfg.vault_path}\n"
        )
        parts.append(runtime_info)

        # 读取 schema.md（从 vault）
        if self.vault.config.schema_path.exists():
            schema = self.vault.config.schema_path.read_text(encoding="utf-8")
            parts.append(f"\n## 知识库 Schema\n\n{schema}")

        # 读取 skill prompts
        skill_prompts = self.vault.get_skill_prompts()
        if skill_prompts:
            parts.append("\n## Skill 扩展能力\n")
            for name, prompt in skill_prompts.items():
                parts.append(f"\n### {name}\n\n{prompt}")

        return "\n".join(parts)

    async def run(self, user_input: str) -> str:
        """执行一轮对话。

        Args:
            user_input: 用户输入

        Returns:
            Agent 最终回复
        """
        self.steps = []
        messages: list[AgentMessage] = [
            AgentMessage(role="system", content=self._system_prompt),
            AgentMessage(role="user", content=user_input),
        ]

        for step_num in range(MAX_STEPS):
            # Think: LLM 决定下一步
            self.on_step(f"思考中... (step {step_num + 1})")
            response_text = await self._call_llm(messages)

            # 解析 LLM 响应：是最终回复还是工具调用
            action_call = self._parse_action(response_text)

            if action_call is None:
                # 最终回复 — 任务完成
                step = AgentStep(thought=response_text)
                self.steps.append(step)
                return response_text

            action_name, params = action_call
            step = AgentStep(
                thought=response_text,
                action=action_name,
                params=params,
            )

            # Act: 执行工具
            params_short = ", ".join(
                f"{k}={repr(v)[:50]}" for k, v in (params or {}).items()
            )
            self.on_step(f"执行: {action_name}({params_short})")
            result = await self.executor.execute(action_name, params)
            step.result = result
            self.steps.append(step)

            # Observe: 把 assistant 回复和工具结果加入消息历史
            messages.append(AgentMessage(role="assistant", content=response_text))

            # 接近步数上限时提醒 Agent 尽快收尾
            result_prefix = ""
            if step_num >= _WARN_AT_STEP - 1:
                remaining = MAX_STEPS - step_num - 1
                result_prefix = (
                    f"[系统提醒: 还剩 {remaining} 步就到上限了，请尽快总结回复用户。]\n"
                )

            messages.append(
                AgentMessage(
                    role="user",
                    content=f"{result_prefix}[工具 {action_name} 执行结果]\n{result}",
                )
            )

        # 达到最大步数，汇总已完成的操作
        completed = []
        for s in self.steps:
            if s.action and s.result:
                completed.append(f"- {s.action}: {s.result[:100]}")
        summary = "\n".join(completed[-5:]) if completed else "无"
        return f"已执行 {len(self.steps)} 步，以下是最近完成的操作:\n{summary}"

    async def _call_llm(self, messages: list[AgentMessage]) -> str:
        """调用 LLM（通过统一的 LLMClient 接口）。"""
        api_messages = []
        for msg in messages:
            role = msg.role
            if role == "tool_result":
                role = "user"
            api_messages.append({"role": role, "content": msg.content})

        return await self.llm.chat_messages(api_messages, max_tokens=4096)

    @staticmethod
    def _parse_action(text: str) -> tuple[str, dict] | None:
        """解析 LLM 响应中的 action 调用。

        如果包含 {"action": "xxx", "params": {...}} 则返回 (action, params)。
        否则返回 None（表示最终回复）。
        """
        # 尝试从 ```json ``` 中提取
        m = re.search(r"```(?:json)?\s*\n?(.*?)\n?```", text, re.DOTALL)
        if m:
            try:
                data = json.loads(m.group(1))
                if "action" in data:
                    return data["action"], data.get("params", {})
            except json.JSONDecodeError:
                pass

        # 尝试直接匹配 JSON
        m = re.search(r'\{"action"\s*:', text)
        if m:
            start = m.start()
            # 找到对应的 }
            brace_count = 0
            for i in range(start, len(text)):
                if text[i] == "{":
                    brace_count += 1
                elif text[i] == "}":
                    brace_count -= 1
                    if brace_count == 0:
                        try:
                            data = json.loads(text[start : i + 1])
                            if "action" in data:
                                return data["action"], data.get("params", {})
                        except json.JSONDecodeError:
                            pass
                        break

        return None
