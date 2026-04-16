"""
Skill 共享工具函数。
"""

from __future__ import annotations

from urllib.parse import parse_qs, unquote, urlparse

# 安全跳转域名（飞书/微信/知乎等）
_REDIRECT_HOSTS = {
    "security.feishu.cn",
    "link.zhihu.com",
    "weixin110.qq.com",
}


def unwrap_url(url: str) -> str:
    """从飞书/微信/知乎等安全跳转链接中提取真实 URL。"""
    try:
        parsed = urlparse(url)
        if parsed.hostname in _REDIRECT_HOSTS:
            params = parse_qs(parsed.query)
            target = params.get("target", [None])[0]
            if target:
                return unquote(target)
    except Exception:
        pass
    return url
