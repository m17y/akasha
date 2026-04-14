"""
CLI 接入层 — 终端交互。

用法:
    akasha-cli                     进入对话模式
    akasha-cli search "Agent"      单次命令
    akasha-cli status              查看状态
"""

import asyncio
import logging
import sys

from ..vault import Vault

# 关掉 httpx 的 INFO 日志（HTTP Request: POST ... 200 OK）
logging.getLogger("httpx").setLevel(logging.WARNING)


# ---------------------------------------------------------------------------
# 交互式对话模式
# ---------------------------------------------------------------------------


def _repl(vault: Vault):
    """交互式对话循环。"""
    vault.init()
    vault.ensure_indexed()
    vault.load_skills()

    s = vault.status()
    print(f"Akasha — {s['files_count']} 个文件, {s['chunks_count']} 个 chunks")
    if s["llm_configured"]:
        print(f"LLM: {s['llm_model']}")
    else:
        print("LLM: 未配置（搜索可用，ingest/ask 不可用）")
    print()
    print("输入问题或命令（/help 查看命令，/quit 退出）")
    print()

    while True:
        try:
            text = input("akasha> ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\n再见。")
            break

        if not text:
            continue

        if text in ("/quit", "/exit", "/q"):
            print("再见。")
            break

        if text == "/help":
            _print_repl_help()
            continue

        if text == "/status":
            print(vault.status_formatted())
            continue

        if text == "/list":
            print(vault.list_notes_formatted())
            continue

        if text == "/lint":
            print(vault.lint())
            continue

        if text.startswith("/search "):
            query = text[8:].strip()
            if query:
                print(vault.search_formatted(query))
            else:
                print("用法: /search <查询内容>")
            continue

        if text.startswith("/read "):
            path = text[6:].strip()
            if path:
                print(vault.read_formatted(path))
            else:
                print("用法: /read <文件路径>")
            continue

        if text.startswith("/ingest "):
            path = text[8:].strip()
            if path:
                try:
                    result = asyncio.run(vault.ingest(path))
                    print(result)
                except Exception as e:
                    print(f"摄入失败: {e}")
            else:
                print("用法: /ingest <文件路径>")
            continue

        # 非命令文本：有 LLM 时走 Agent，否则当搜索
        if s["llm_configured"]:

            def _on_step(msg):
                print(f"  [{msg}]", flush=True)

            try:
                result = asyncio.run(vault.ask(text, on_step=_on_step))
                print(result)
            except Exception as e:
                print(f"Agent 调用失败: {e}")
                print("回退到搜索模式...")
                print(vault.search_formatted(text))
        else:
            print(vault.search_formatted(text))

        print()


def _print_repl_help():
    print()
    print("命令:")
    print("  /search <内容>   搜索知识库")
    print("  /list            列出所有笔记")
    print("  /read <路径>     读取笔记")
    print("  /ingest <路径>   摄入文档（需要 LLM）")
    print("  /lint            Wiki 健康检查")
    print("  /status          查看状态")
    print("  /help            显示此帮助")
    print("  /quit            退出")
    print()
    print("直接输入文字：有 LLM 时走 Agent 对话，无 LLM 时当搜索")
    print()


# ---------------------------------------------------------------------------
# 单次命令模式
# ---------------------------------------------------------------------------


def main():
    # 无参数 → 进入对话模式
    if len(sys.argv) < 2:
        vault = Vault()
        _repl(vault)
        return

    cmd = sys.argv[1]
    vault = Vault()

    if cmd in ("help", "--help", "-h"):
        _print_help()

    elif cmd == "init":
        vault.init()
        print(vault.status_formatted())
        print("\nvault 初始化完成。")

    elif cmd == "status":
        vault.init()
        vault.ensure_indexed()
        print(vault.status_formatted())

    elif cmd == "search":
        if len(sys.argv) < 3:
            print("用法: akasha-cli search <query>")
            sys.exit(1)
        query = " ".join(sys.argv[2:])
        vault.ensure_indexed()
        print(vault.search_formatted(query))

    elif cmd == "list":
        vault.ensure_indexed()
        print(vault.list_notes_formatted())

    elif cmd == "read":
        if len(sys.argv) < 3:
            print("用法: akasha-cli read <file_path>")
            sys.exit(1)
        print(vault.read_formatted(sys.argv[2]))

    elif cmd == "lint":
        vault.init()
        print(vault.lint())

    elif cmd == "ask":
        if len(sys.argv) < 3:
            print("用法: akasha-cli ask <message>")
            sys.exit(1)
        message = " ".join(sys.argv[2:])
        result = asyncio.run(vault.ask(message))
        print(result)

    else:
        print(f"未知命令: {cmd}")
        _print_help()
        sys.exit(1)


def _print_help():
    print("Akasha CLI — 个人 AI 知识库")
    print()
    print("用法:")
    print("  akasha-cli                   进入对话模式")
    print("  akasha-cli init              初始化 vault")
    print("  akasha-cli status            查看状态")
    print("  akasha-cli search <query>    搜索笔记")
    print("  akasha-cli list              列出所有笔记")
    print("  akasha-cli read <path>       读取笔记")
    print("  akasha-cli lint              Wiki 健康检查")
    print("  akasha-cli ask <message>     单次 Agent 对话")
    print("  akasha-cli help              显示此帮助")
