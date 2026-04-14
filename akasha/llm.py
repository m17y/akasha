"""
LLM 客户端 — 支持多 provider。

通过 AKASHA_LLM_PROVIDER 环境变量选择:
- "openai"    (默认) — 任何 OpenAI 兼容端点
- "anthropic"         — Anthropic API（含 MiniMax M2.7 兼容）

L5 韧性:
- 自动重试（max_retries=3）
- 请求超时（默认 120s）
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from .config import Config


class LLMClient(ABC):
    """LLM 客户端抽象基类。"""

    @abstractmethod
    async def chat(
        self,
        system: str,
        user: str,
        temperature: float | None = None,
        max_tokens: int = 4096,
    ) -> str:
        """单轮对话，返回文本结果。"""

    @abstractmethod
    async def chat_with_context(
        self,
        system: str,
        context: str,
        user: str,
        temperature: float | None = None,
        max_tokens: int = 4096,
    ) -> str:
        """带上下文的对话（system + context + user 三段）。"""

    @abstractmethod
    async def chat_messages(
        self,
        messages: list[dict],
        max_tokens: int = 4096,
        temperature: float | None = None,
    ) -> str:
        """多轮对话，传入完整 messages 列表。"""


class OpenAIClient(LLMClient):
    """OpenAI 兼容 API 客户端。"""

    def __init__(self, config: Config):
        from openai import AsyncOpenAI

        self._client = AsyncOpenAI(
            api_key=config.llm_api_key,
            base_url=config.llm_base_url_resolved,
            timeout=120.0,
            max_retries=3,
        )
        self._model = config.llm_model_resolved

    async def chat(self, system, user, temperature=None, max_tokens=4096):
        kwargs: dict = {
            "model": self._model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "max_tokens": max_tokens,
        }
        if temperature is not None:
            kwargs["temperature"] = temperature
        resp = await self._client.chat.completions.create(**kwargs)
        return resp.choices[0].message.content or ""

    async def chat_with_context(
        self, system, context, user, temperature=None, max_tokens=4096
    ):
        kwargs: dict = {
            "model": self._model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": f"以下是相关上下文:\n\n{context}"},
                {"role": "assistant", "content": "已理解上下文，请告诉我你需要什么。"},
                {"role": "user", "content": user},
            ],
            "max_tokens": max_tokens,
        }
        if temperature is not None:
            kwargs["temperature"] = temperature
        resp = await self._client.chat.completions.create(**kwargs)
        return resp.choices[0].message.content or ""

    async def chat_messages(self, messages, max_tokens=4096, temperature=None):
        kwargs: dict = {
            "model": self._model,
            "messages": messages,
            "max_tokens": max_tokens,
        }
        if temperature is not None:
            kwargs["temperature"] = temperature
        resp = await self._client.chat.completions.create(**kwargs)
        return resp.choices[0].message.content or ""


class AnthropicClient(LLMClient):
    """Anthropic API 客户端（支持 Anthropic 原生 + MiniMax 兼容）。"""

    def __init__(self, config: Config):
        from anthropic import AsyncAnthropic

        self._client = AsyncAnthropic(
            api_key=config.llm_api_key,
            base_url=config.llm_base_url_resolved,
            timeout=120.0,
            max_retries=3,
        )
        self._model = config.llm_model_resolved

    async def chat(self, system, user, temperature=None, max_tokens=4096):
        kwargs: dict = {
            "model": self._model,
            "system": system,
            "messages": [{"role": "user", "content": user}],
            "max_tokens": max_tokens,
        }
        if temperature is not None:
            kwargs["temperature"] = temperature
        resp = await self._client.messages.create(**kwargs)
        return self._extract_text(resp)

    async def chat_with_context(
        self, system, context, user, temperature=None, max_tokens=4096
    ):
        kwargs: dict = {
            "model": self._model,
            "system": system,
            "messages": [
                {"role": "user", "content": f"以下是相关上下文:\n\n{context}"},
                {"role": "assistant", "content": "已理解上下文，请告诉我你需要什么。"},
                {"role": "user", "content": user},
            ],
            "max_tokens": max_tokens,
        }
        if temperature is not None:
            kwargs["temperature"] = temperature
        resp = await self._client.messages.create(**kwargs)
        return self._extract_text(resp)

    async def chat_messages(self, messages, max_tokens=4096, temperature=None):
        # Anthropic 格式: system 单独提取，messages 只含 user/assistant
        system = ""
        api_messages = []
        for msg in messages:
            if msg["role"] == "system":
                system = msg["content"]
            else:
                api_messages.append(
                    {
                        "role": msg["role"],
                        "content": msg["content"],
                    }
                )

        kwargs: dict = {
            "model": self._model,
            "messages": api_messages,
            "max_tokens": max_tokens,
        }
        if system:
            kwargs["system"] = system
        if temperature is not None:
            kwargs["temperature"] = temperature
        resp = await self._client.messages.create(**kwargs)
        return self._extract_text(resp)

    @staticmethod
    def _extract_text(resp) -> str:
        """从 Anthropic 响应中提取文本。"""
        parts = []
        for block in resp.content:
            if hasattr(block, "text"):
                parts.append(block.text)
        return "\n".join(parts) if parts else ""


def create_llm_client(config: Config) -> LLMClient:
    """根据配置创建对应的 LLM 客户端。"""
    if not config.llm_configured:
        raise RuntimeError(
            "LLM 未配置。请设置环境变量:\n"
            "  AKASHA_LLM_API_KEY=sk-xxx\n"
            "  AKASHA_LLM_PROVIDER=openai|anthropic  (可选，默认 openai)\n"
            "  AKASHA_LLM_BASE_URL=...  (可选)\n"
            "  AKASHA_LLM_MODEL=...  (可选)"
        )

    provider = config.llm_provider.lower()
    if provider == "anthropic":
        return AnthropicClient(config)
    else:
        return OpenAIClient(config)
