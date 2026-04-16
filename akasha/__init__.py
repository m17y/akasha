"""Akasha — 个人 AI 知识库引擎。"""

import threading

from .vault import Vault

__all__ = ["Vault"]


_llm_client_cache = None
_llm_client_lock = threading.Lock()


def _get_llm_client():
    """获取 LLM 客户端实例（供 skill 等内部模块使用）。单例缓存，线程安全。"""
    global _llm_client_cache
    if _llm_client_cache is not None:
        return _llm_client_cache

    with _llm_client_lock:
        # Double-check after acquiring lock
        if _llm_client_cache is not None:
            return _llm_client_cache

        from .config import load_config
        from .llm import create_llm_client

        config = load_config()
        if not config.llm_configured:
            return None
        _llm_client_cache = create_llm_client(config)
        return _llm_client_cache
