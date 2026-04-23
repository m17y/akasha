"""
飞书 Bot 接入层 — WebSocket 长连接模式。

不需要公网 IP，不需要 webhook，直接和飞书服务器保持长连接。

启动:
  akasha-feishu

环境变量:
  AKASHA_FEISHU_APP_ID         飞书应用 App ID
  AKASHA_FEISHU_APP_SECRET     飞书应用 App Secret
  AKASHA_FEISHU_BOT_NAME       Bot 名称（默认 Akasha）
  AKASHA_*                     Akasha 核心配置

飞书开放平台配置:
  1. 创建企业自建应用 → 添加 Bot 能力
  2. 事件订阅 → 订阅方式选「使用长连接接收事件」
  3. 订阅事件: im.message.receive_v1
  4. 权限: im:message:send_as_bot
"""

from __future__ import annotations

import asyncio
import concurrent.futures
import json
import os
import sys
import threading
from dataclasses import dataclass, field

import lark_oapi as lark
from lark_oapi.api.im.v1 import (
    CreateMessageReactionRequest,
    CreateMessageReactionRequestBody,
    ReplyMessageRequest,
    ReplyMessageRequestBody,
    Emoji,
    P2ImMessageReceiveV1,
    P2ImMessageReactionCreatedV1,
)
from lark_oapi.event.dispatcher_handler import EventDispatcherHandler
from lark_oapi.ws import Client as WsClient

from ..vault import Vault


# ---------------------------------------------------------------------------
# 配置
# ---------------------------------------------------------------------------


@dataclass
class FeishuConfig:
    """飞书 Bot 配置。"""

    app_id: str = field(default_factory=lambda: os.getenv("AKASHA_FEISHU_APP_ID", ""))
    app_secret: str = field(
        default_factory=lambda: os.getenv("AKASHA_FEISHU_APP_SECRET", "")
    )
    encrypt_key: str = field(
        default_factory=lambda: os.getenv("AKASHA_FEISHU_ENCRYPT_KEY", "")
    )
    verification_token: str = field(
        default_factory=lambda: os.getenv("AKASHA_FEISHU_VERIFICATION_TOKEN", "")
    )
    bot_name: str = field(
        default_factory=lambda: os.getenv("AKASHA_FEISHU_BOT_NAME", "Akasha")
    )

    @property
    def configured(self) -> bool:
        return bool(self.app_id and self.app_secret)


# ---------------------------------------------------------------------------
# 命令处理器 — 全部转发给 Vault
# ---------------------------------------------------------------------------


def _run_async(coro):
    """在独立线程里运行 async 协程。

    飞书 WsClient 的回调已经在 event loop 内，不能直接
    run_until_complete，必须在新线程里创建独立 event loop。
    """

    def _runner():
        loop = asyncio.new_event_loop()
        try:
            return loop.run_until_complete(coro)
        finally:
            loop.close()

    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(_runner)
        return future.result(timeout=600)  # 视频下载+转写可能需要较长时间


class FeishuHandlers:
    """飞书命令处理器（全部同步，因为 WS 回调在 event loop 内）。"""

    def __init__(self, vault: Vault):
        self.vault = vault

    def dispatch(self, text: str, user_id: str = "") -> str:
        """路由消息到对应 handler。"""
        text = text.strip()

        if text.startswith("/"):
            parts = text.split(maxsplit=1)
            cmd = parts[0].lower()
            arg = parts[1].strip() if len(parts) > 1 else ""

            routes = {
                "/search": lambda: self.search(arg),
                "/clip": lambda: self.clip(arg),
                "/video": lambda: self.video(arg),
                "/ingest": lambda: self.ingest(arg),
                "/status": lambda: self.status(),
                "/lint": lambda: self.lint(),
                "/help": lambda: self.help(),
            }

            handler = routes.get(cmd)
            if handler:
                return handler()
            return f"未知命令: {cmd}\n输入 /help 查看可用命令"

        # 非命令消息：有 LLM 走 Agent，否则当搜索
        if len(text) > 2:
            if self.vault.config.llm_configured:
                return self.ask(text, user_id=user_id)
            return self.search(text)

        return self.help()

    def ask(self, message: str, user_id: str = "") -> str:
        """Agent 模式 — 自然语言交互。"""
        try:
            return _run_async(self.vault.ask(message, user_id=user_id))
        except Exception as e:
            import traceback

            tb = traceback.format_exc()
            print(f"[feishu] Agent 失败: {e}\n{tb}", file=sys.stderr)
            search_result = self.search(message)
            return (
                f"[Agent 暂不可用，回退搜索]\n"
                f"[错误: {type(e).__name__}: {e}]\n\n"
                f"{search_result}"
            )

    def search(self, query: str) -> str:
        if not query:
            return "用法: /search <查询内容>\n示例: /search Agent Loop 设计模式"
        return self.vault.search_formatted(query)

    def clip(self, url: str) -> str:
        if not url:
            return (
                "用法: /clip <网页链接>\n示例: /clip https://blog.example.com/article"
            )
        try:
            return f"已保存: {_run_async(self.vault.execute_skill('web_clip_save', url=url))}"
        except Exception as e:
            return f"剪藏失败: {e}"

    def video(self, url: str) -> str:
        if not url:
            return (
                "用法: /video <视频链接>\n示例: /video https://www.douyin.com/video/xxx"
            )
        try:
            return f"已生成: {_run_async(self.vault.execute_skill('video_to_wiki', url=url))}"
        except Exception as e:
            return f"视频处理失败: {e}"

    def ingest(self, file_path: str) -> str:
        if not file_path:
            return "用法: /ingest <文件路径>\n示例: /ingest raw/analysis/xxx.md"
        try:
            return _run_async(self.vault.ingest(file_path))
        except Exception as e:
            return f"摄入失败: {e}"

    def status(self) -> str:
        return self.vault.status_formatted()

    def lint(self) -> str:
        return self.vault.lint()

    def help(self) -> str:
        return (
            "Akasha 飞书 Bot\n\n"
            "命令:\n"
            "  /search <内容>  搜索知识库\n"
            "  /clip <链接>    剪藏网页\n"
            "  /video <链接>   下载视频 + 生成 wiki\n"
            "  /ingest <路径>  摄入文档到知识库\n"
            "  /status         知识库状态\n"
            "  /lint           Wiki 健康检查\n"
            "  /help           显示帮助"
        )


# ---------------------------------------------------------------------------
# 全局状态（线程安全：所有惰性初始化都在锁内完成）
# ---------------------------------------------------------------------------

_init_lock = threading.Lock()
_feishu_config: FeishuConfig | None = None
_vault: Vault | None = None
_handlers: FeishuHandlers | None = None
_lark_client: lark.Client | None = None


def _get_feishu_config() -> FeishuConfig:
    global _feishu_config
    if _feishu_config is not None:
        return _feishu_config
    with _init_lock:
        if _feishu_config is None:
            _feishu_config = FeishuConfig()
        return _feishu_config


def _get_vault() -> Vault:
    global _vault
    if _vault is not None:
        return _vault
    with _init_lock:
        if _vault is None:
            v = Vault()
            v.init()
            v.ensure_indexed()
            v.load_skills()
            _vault = v
        return _vault


def _get_handlers() -> FeishuHandlers:
    global _handlers
    if _handlers is not None:
        return _handlers
    with _init_lock:
        if _handlers is None:
            _handlers = FeishuHandlers(_get_vault())
        return _handlers


def _get_lark_client() -> lark.Client:
    global _lark_client
    if _lark_client is not None:
        return _lark_client
    with _init_lock:
        if _lark_client is None:
            cfg = _get_feishu_config()
            _lark_client = (
                lark.Client.builder()
                .app_id(cfg.app_id)
                .app_secret(cfg.app_secret)
                .build()
            )
        return _lark_client


# ---------------------------------------------------------------------------
# 消息回复
# ---------------------------------------------------------------------------


def _add_reaction(message_id: str, emoji_type: str = "OnIt") -> None:
    """给消息加表情回应，表示收到了。"""
    client = _get_lark_client()
    body = (
        CreateMessageReactionRequestBody.builder()
        .reaction_type(Emoji.builder().emoji_type(emoji_type).build())
        .build()
    )
    request = (
        CreateMessageReactionRequest.builder()
        .message_id(message_id)
        .request_body(body)
        .build()
    )
    response = client.im.v1.message_reaction.create(request)
    if not response.success():
        print(f"[feishu] 添加表情失败: {response.code} {response.msg}", file=sys.stderr)


def _send_reply(message_id: str, text: str) -> None:
    """回复飞书消息（同步调用）。超长消息自动分段。"""
    MAX_LEN = 3500  # 飞书文本消息限制约 4000 字符，留余量

    if len(text) <= MAX_LEN:
        _send_reply_raw(message_id, text)
    else:
        # 分段发送
        parts = []
        while text:
            if len(text) <= MAX_LEN:
                parts.append(text)
                break
            # 在换行符处截断
            cut = text.rfind("\n", 0, MAX_LEN)
            if cut <= 0:
                cut = MAX_LEN
            parts.append(text[:cut])
            text = text[cut:].lstrip("\n")

        for i, part in enumerate(parts):
            if len(parts) > 1:
                part = f"({i + 1}/{len(parts)})\n{part}"
            _send_reply_raw(message_id, part)


def _send_reply_raw(message_id: str, text: str) -> None:
    """发送单条飞书回复。"""
    client = _get_lark_client()
    body = (
        ReplyMessageRequestBody.builder()
        .msg_type("text")
        .content(json.dumps({"text": text}))
        .build()
    )
    request = (
        ReplyMessageRequest.builder().message_id(message_id).request_body(body).build()
    )
    response = client.im.v1.message.reply(request)
    if not response.success():
        print(f"[feishu] 回复失败: {response.code} {response.msg}", file=sys.stderr)


# ---------------------------------------------------------------------------
# 事件处理 — 消息去重
# ---------------------------------------------------------------------------

# 已处理的 message_id 缓存（防止飞书重复推送）
_processed_messages: set[str] = set()
_processed_messages_lock = threading.Lock()
_MAX_CACHE_SIZE = 500


def _is_duplicate(message_id: str) -> bool:
    """检查消息是否已处理过（线程安全）。"""
    with _processed_messages_lock:
        if message_id in _processed_messages:
            return True
        _processed_messages.add(message_id)
        # 防止缓存无限增长
        if len(_processed_messages) > _MAX_CACHE_SIZE:
            # 清掉一半（set 无序，直接 pop）
            for _ in range(_MAX_CACHE_SIZE // 2):
                _processed_messages.pop()
        return False


def _handle_message(
    message_id: str, chat_type: str, text: str, user_id: str = ""
) -> None:
    """在后台线程中处理消息（耗时操作不阻塞 WsClient 回调）。"""
    # 先加表情表示收到了
    _add_reaction(message_id, "OnIt")

    # 文件消息处理
    if text.startswith("[file:"):
        reply = _handle_file_message(text, message_id, user_id)
    else:
        # 路由到 handler
        handlers = _get_handlers()
        try:
            reply = handlers.dispatch(text, user_id=user_id)
        except Exception as e:
            reply = f"处理失败: {e}"

    # 回复
    if reply and message_id:
        _send_reply(message_id, reply)
        print(f"[feishu] 已回复: msg_id={message_id} len={len(reply)}", flush=True)


def _handle_file_message(text: str, message_id: str, user_id: str) -> str:
    """处理文件消息：下载文件 → 根据类型处理。"""
    import re
    import tempfile

    m = re.match(r"\[file:(.+?):(.+?)\]", text)
    if not m:
        return "无法解析文件信息"

    file_name = m.group(1)
    file_key = m.group(2)

    # 只支持 PDF
    if not file_name.lower().endswith(".pdf"):
        return f"暂不支持 {file_name.split('.')[-1]} 格式，目前只支持 PDF"

    tmp_dir = None
    try:
        # 下载文件
        client = _get_lark_client()
        from lark_oapi.api.im.v1 import GetMessageResourceRequest

        req = (
            GetMessageResourceRequest.builder()
            .message_id(message_id)
            .file_key(file_key)
            .type("file")
            .build()
        )
        resp = client.im.v1.message_resource.get(req)

        if not resp.success():
            return f"下载文件失败: {resp.msg}"

        # 保存到临时文件
        tmp_dir = tempfile.mkdtemp()
        tmp_path = f"{tmp_dir}/{file_name}"
        with open(tmp_path, "wb") as f:
            f.write(resp.file.read())

        print(f"[feishu] 已下载文件: {file_name} → {tmp_path}", flush=True)

        # 调用 pdf_to_wiki
        vault = _get_vault()

        def _run():
            import asyncio

            loop = asyncio.new_event_loop()
            try:
                return loop.run_until_complete(
                    vault.execute_skill("pdf_to_wiki", file_path=tmp_path)
                )
            finally:
                loop.close()

        from concurrent.futures import ThreadPoolExecutor

        with ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(_run)
            result = future.result(timeout=600)

        return f"已处理 PDF: {result}"

    except Exception as e:
        return f"PDF 处理失败: {e}"
    finally:
        # 清理临时文件
        if tmp_dir:
            import shutil
            shutil.rmtree(tmp_dir, ignore_errors=True)


def _on_message_receive(data: P2ImMessageReceiveV1) -> None:
    """处理收到的消息事件。立即返回，耗时操作在后台线程执行。"""
    message = data.event.message
    message_id = message.message_id
    message_type = message.message_type
    chat_type = message.chat_type

    # 消息去重
    if _is_duplicate(message_id):
        print(f"[feishu] 重复消息，跳过: msg_id={message_id}", flush=True)
        return

    # 解析消息内容
    text = ""
    file_key = ""
    file_name = ""

    if message_type == "text":
        try:
            content = json.loads(message.content or "{}")
            text = content.get("text", "").strip()
        except json.JSONDecodeError:
            text = ""
    elif message_type == "post":
        # 富文本消息（长文本、带格式的消息）
        try:
            content = json.loads(message.content or "{}")
            # post 格式: {"zh_cn": {"title": "...", "content": [[{"tag":"text","text":"..."}]]}}
            post = content.get("zh_cn") or content.get("en_us") or {}
            title = post.get("title", "")
            paragraphs = post.get("content", [])
            parts = []
            if title:
                parts.append(title)
            for para in paragraphs:
                for elem in para:
                    if elem.get("tag") == "text":
                        parts.append(elem.get("text", ""))
                    elif elem.get("tag") == "a":
                        parts.append(elem.get("href", ""))
                    elif elem.get("tag") == "at":
                        pass  # 跳过 @提及
            text = "\n".join(parts).strip()
        except (json.JSONDecodeError, Exception):
            text = ""
    elif message_type == "file":
        # 文件消息：下载并处理
        try:
            content = json.loads(message.content or "{}")
            file_key = content.get("file_key", "")
            file_name = content.get("file_name", "")
        except json.JSONDecodeError:
            pass
        if file_key and file_name:
            text = f"[file:{file_name}:{file_key}]"
        else:
            print("[feishu] 收到文件消息但缺少 file_key/file_name，跳过", flush=True)
            return
    else:
        print(f"[feishu] 收到非文本消息: type={message_type}, 跳过", flush=True)
        return

    if not text:
        return

    # 群聊去掉 @Bot 前缀
    if chat_type == "group" and text.startswith("@"):
        parts = text.split(" ", 1)
        text = parts[1].strip() if len(parts) > 1 else ""
        if not text:
            return

    # 提取发送者 ID（用于会话记忆）
    sender = data.event.sender
    user_id = ""
    if sender and hasattr(sender, "sender_id") and sender.sender_id:
        user_id = getattr(sender.sender_id, "open_id", "") or ""

    print(
        f"[feishu] 收到消息: chat={chat_type} msg_id={message_id} user={user_id[:10]} text={text!r}",
        flush=True,
    )

    # 在后台线程处理，不阻塞 WsClient 回调
    thread = threading.Thread(
        target=_handle_message,
        args=(message_id, chat_type, text, user_id),
        daemon=True,
    )
    thread.start()


# ---------------------------------------------------------------------------
# 入口
# ---------------------------------------------------------------------------


def main():
    cfg = _get_feishu_config()

    if not cfg.configured:
        print("[feishu] 未配置，跳过飞书通道")
        print("[feishu] 设置 AKASHA_FEISHU_APP_ID + AKASHA_FEISHU_APP_SECRET 启用")
        return

    # 初始化 vault
    vault = _get_vault()
    print(f"[feishu] bot: {cfg.bot_name}")
    print(f"[feishu] vault: {vault.config.vault_path}")

    # 注册事件处理器
    def _on_reaction_created(data: P2ImMessageReactionCreatedV1) -> None:
        pass  # 忽略表情事件

    event_handler = (
        EventDispatcherHandler.builder(cfg.encrypt_key, cfg.verification_token)
        .register_p2_im_message_receive_v1(_on_message_receive)
        .register_p2_im_message_reaction_created_v1(_on_reaction_created)
        .build()
    )

    # 启动 WebSocket 长连接
    ws_client = WsClient(
        app_id=cfg.app_id,
        app_secret=cfg.app_secret,
        event_handler=event_handler,
        log_level=lark.LogLevel.INFO,
        auto_reconnect=True,
    )

    print("[feishu] 连接飞书服务器...")
    ws_client.start()


if __name__ == "__main__":
    main()
