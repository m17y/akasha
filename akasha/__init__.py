"""Akasha — 个人 AI 知识库引擎。"""

from .vault import Vault

__all__ = ["Vault"]


def _get_llm_client():
    """获取 LLM 客户端实例（供 skill 等内部模块使用）。"""
    from .config import load_config
    from .llm import create_llm_client

    config = load_config()
    if not config.llm_configured:
        return None
    return create_llm_client(config)
