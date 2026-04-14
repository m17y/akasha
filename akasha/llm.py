"""
LLM 客户端 — 封装 OpenAI 兼容 API。

支持任何 OpenAI 兼容端点（OpenAI / Azure / Mify 代理 / Ollama 等）。
用于 ingest、save_as_page、lint_wiki 等需要 LLM 推理的操作。

L5 韧性:
- 自动重试（max_retries=3，SDK 内置指数退避）
- 请求超时（默认 120s）
- 结构化错误日志
"""

from __future__ import annotations

from openai import AsyncOpenAI

from .config import Config


class LLMClient:
    """异步 LLM 客户端，内置重试和超时。"""

    def __init__(self, config: Config):
        if not config.llm_configured:
            raise RuntimeError(
                "LLM 未配置。请设置环境变量:\n"
                "  AKASHA_LLM_API_KEY=sk-xxx\n"
                "  AKASHA_LLM_BASE_URL=https://api.openai.com/v1  (可选)\n"
                "  AKASHA_LLM_MODEL=gpt-4o  (可选)"
            )
        self._client = AsyncOpenAI(
            api_key=config.llm_api_key,
            base_url=config.llm_base_url,
            timeout=120.0,  # L5: 请求超时 120 秒
            max_retries=3,  # L5: 自动重试 3 次（429/500/502/503）
        )
        self._model = config.llm_model

    async def chat(
        self,
        system: str,
        user: str,
        temperature: float = 0.3,
        max_tokens: int = 4096,
    ) -> str:
        """单轮对话，返回文本结果。

        Args:
            system: 系统提示词
            user: 用户消息
            temperature: 生成温度（低 = 更确定性）
            max_tokens: 最大输出 token 数

        Returns:
            LLM 生成的文本
        """
        resp = await self._client.chat.completions.create(
            model=self._model,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            temperature=temperature,
            max_tokens=max_tokens,
        )
        return resp.choices[0].message.content or ""

    async def chat_with_context(
        self,
        system: str,
        context: str,
        user: str,
        temperature: float = 0.3,
        max_tokens: int = 4096,
    ) -> str:
        """带上下文的对话（system + context + user 三段）。

        Args:
            system: 系统提示词（角色和规则）
            context: 上下文内容（如已有 wiki 页面）
            user: 用户指令

        Returns:
            LLM 生成的文本
        """
        resp = await self._client.chat.completions.create(
            model=self._model,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": f"以下是相关上下文:\n\n{context}"},
                {"role": "assistant", "content": "已理解上下文，请告诉我你需要什么。"},
                {"role": "user", "content": user},
            ],
            temperature=temperature,
            max_tokens=max_tokens,
        )
        return resp.choices[0].message.content or ""
