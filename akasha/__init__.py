"""Akasha — 个人 AI 知识库引擎。"""

from .vault import Vault

__all__ = ["Vault"]


_llm_client_cache = None


def _get_llm_client():
    """获取 LLM 客户端实例（供 skill 等内部模块使用）。单例缓存。"""
    global _llm_client_cache
    if _llm_client_cache is not None:
        return _llm_client_cache

    from .config import load_config
    from .llm import create_llm_client

    config = load_config()
    if not config.llm_configured:
        return None
    _llm_client_cache = create_llm_client(config)
    return _llm_client_cache
