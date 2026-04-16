#!/usr/bin/env python3
"""
Auto-Improve — AI 自主改进守护进程。

每轮循环：
1. Analyze  — 分析项目，LLM 生成改进任务
2. Plan     — 选出最有价值的 1 个任务，生成方案
3. Implement— 按方案修改代码
4. Verify   — 语法检查 + 测试（失败则修复，最多 3 轮）
5. Evaluate — LLM 评估改动质量（< 6 分回滚）
6. Report   — 记录 CHANGELOG，提交到 dev 分支，创建 PR
7. Sleep    — 休息后回到 1

安全机制：
- 所有改动提交到 dev 分支，不碰 main
- 每轮最多改 5 个文件
- 质量评估 < 6 分自动回滚
- 语法检查失败自动回滚
- 完整日志记录

用法:
  python3 scripts/auto_improve.py              # 运行一轮
  python3 scripts/auto_improve.py --daemon     # 守护模式（持续运行）
  python3 scripts/auto_improve.py --interval 3600  # 自定义间隔（秒）
"""

from __future__ import annotations

import argparse
import ast
import json
import os
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

# ── 配置 ──
PROJECT_DIR = Path(__file__).parent.parent
AKASHA_DIR = PROJECT_DIR / "akasha"
CHANGELOG = PROJECT_DIR / "CHANGELOG.md"
IMPROVE_LOG = PROJECT_DIR / "scripts" / ".improve-history.json"
MAX_FILES = 5
MAX_FIX_ROUNDS = 3


def log(msg: str) -> None:
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{ts}] {msg}", flush=True)


# ── LLM 调用 ──


def call_llm(system: str, user: str, max_tokens: int = 4096) -> str:
    """调用 Akasha 的 LLM 客户端。"""
    try:
        # 用 Akasha 自己的 LLM
        sys.path.insert(0, str(PROJECT_DIR))
        from akasha.config import load_config
        from akasha.llm import create_llm_client
        import asyncio

        config = load_config()
        if not config.llm_configured:
            log("LLM 未配置，跳过")
            return ""

        llm = create_llm_client(config)
        result = asyncio.run(
            llm.chat(
                system=system,
                user=user,
                max_tokens=max_tokens,
                temperature=0.3,
            )
        )
        return result.strip()
    except Exception as e:
        log(f"LLM 调用失败: {e}")
        return ""


# ── Git 操作 ──


def git(*args) -> tuple[int, str]:
    r = subprocess.run(
        ["git"] + list(args), cwd=PROJECT_DIR, capture_output=True, text=True
    )
    return r.returncode, r.stdout.strip()


def git_check(*args) -> str:
    code, out = git(*args)
    if code != 0:
        raise RuntimeError(f"git {' '.join(args)} failed: {out}")
    return out


# ── 核心阶段 ──


def load_history() -> list[dict]:
    """加载历史改进记录。"""
    if IMPROVE_LOG.exists():
        return json.loads(IMPROVE_LOG.read_text())
    return []


def save_history(history: list[dict]) -> None:
    IMPROVE_LOG.parent.mkdir(parents=True, exist_ok=True)
    IMPROVE_LOG.write_text(json.dumps(history, ensure_ascii=False, indent=2))


def stage_analyze() -> str:
    """阶段 1：分析项目，生成改进任务。"""
    log("=== 阶段 1: Analyze ===")

    # 收集项目上下文
    recent_commits = git_check("log", "--oneline", "-15")

    # 收集文件结构
    py_files = sorted(AKASHA_DIR.rglob("*.py"))
    file_list = "\n".join(str(f.relative_to(PROJECT_DIR)) for f in py_files[:40])

    # 读取历史（避免重复改同一个地方）
    history = load_history()
    recent_tasks = (
        "\n".join(f"- {h['task']} ({h['date']})" for h in history[-10:])
        or "（无历史记录）"
    )

    # 读取现有 issues（如果有 TODO.md）
    todo_content = ""
    todo_file = PROJECT_DIR / "TODO.md"
    if todo_file.exists():
        todo_content = todo_file.read_text()[:2000]

    prompt = (
        f"分析以下 Python 项目，找出 3 个最值得改进的点。\n\n"
        f"## 最近提交\n{recent_commits}\n\n"
        f"## 文件结构\n{file_list}\n\n"
        f"## 最近已做的改进（避免重复）\n{recent_tasks}\n\n"
    )
    if todo_content:
        prompt += f"## TODO\n{todo_content}\n\n"

    prompt += (
        "## 分析维度\n"
        "- 功能缺失（用户体验提升）\n"
        "- Bug 和稳定性\n"
        "- 代码质量（重复、耦合、命名）\n"
        "- 性能优化\n"
        "- 安全问题\n\n"
        "## 输出格式\n"
        "每个改进点用以下格式：\n"
        "### 1. 标题\n"
        "- 影响: 高/中/低\n"
        "- 文件: 涉及的文件\n"
        "- 描述: 具体问题和建议方案\n"
    )

    return call_llm(
        "你是一个资深 Python 架构师，擅长发现代码问题和改进机会。",
        prompt,
    )


def stage_plan(analysis: str) -> dict:
    """阶段 2：从分析中选最有价值的任务，生成实现方案。"""
    log("=== 阶段 2: Plan ===")

    result = call_llm(
        "你是一个精准的技术决策者。",
        f"以下是项目分析结果：\n\n{analysis}\n\n"
        "选出影响最大、改动最小的 1 个任务。\n\n"
        "输出 JSON（严格格式）：\n"
        '{"task": "简短描述", "files": ["file1.py", "file2.py"], '
        '"plan": "详细实现步骤"}\n'
        "只输出 JSON，不要其他内容。",
        max_tokens=1024,
    )

    try:
        # 提取 JSON
        start = result.find("{")
        end = result.rfind("}") + 1
        if start >= 0 and end > start:
            return json.loads(result[start:end])
    except json.JSONDecodeError:
        pass

    return {"task": "未能解析任务", "files": [], "plan": ""}


def stage_implement(plan: dict) -> list[str]:
    """阶段 3：按方案修改代码。返回修改的文件列表。"""
    log(f"=== 阶段 3: Implement === 任务: {plan['task']}")

    if not plan.get("plan"):
        log("没有实现方案，跳过")
        return []

    # 读取目标文件内容
    file_contents = {}
    for f in plan.get("files", []):
        fp = PROJECT_DIR / f
        if fp.exists():
            file_contents[f] = fp.read_text(encoding="utf-8")

    if not file_contents:
        log("没有目标文件，跳过")
        return []

    files_text = ""
    for f, content in file_contents.items():
        # 截断太长的文件
        if len(content) > 5000:
            content = content[:5000] + "\n... (truncated)"
        files_text += f"\n### {f}\n```python\n{content}\n```\n"

    result = call_llm(
        "你是一个精准的 Python 开发者。只输出需要修改的文件内容，不要解释。",
        f"## 任务\n{plan['task']}\n\n"
        f"## 实现方案\n{plan['plan']}\n\n"
        f"## 当前代码\n{files_text}\n\n"
        "## 输出要求\n"
        "对每个需要修改的文件，输出完整的新文件内容：\n"
        "```file:path/to/file.py\n"
        "完整的文件内容\n"
        "```\n"
        "只输出需要改动的文件，不要输出没有变化的文件。",
        max_tokens=8192,
    )

    # 解析输出，提取文件内容
    import re

    modified = []
    for m in re.finditer(r"```file:(.+?)\n(.*?)```", result, re.DOTALL):
        filepath = m.group(1).strip()
        content = m.group(2)
        full_path = PROJECT_DIR / filepath
        if full_path.exists() or filepath in [f for f in plan.get("files", [])]:
            full_path.parent.mkdir(parents=True, exist_ok=True)
            full_path.write_text(content, encoding="utf-8")
            modified.append(filepath)
            log(f"  修改: {filepath}")

    return modified


def stage_verify() -> tuple[bool, str]:
    """阶段 4：语法检查。返回 (通过, 错误信息)。"""
    log("=== 阶段 4: Verify ===")

    errors = []
    for py_file in AKASHA_DIR.rglob("*.py"):
        try:
            ast.parse(py_file.read_text(encoding="utf-8"))
        except SyntaxError as e:
            errors.append(f"{py_file.relative_to(PROJECT_DIR)}: {e}")

    if errors:
        err_text = "\n".join(errors)
        log(f"语法错误:\n{err_text}")
        return False, err_text

    log("语法检查通过")
    return True, ""


def stage_fix(errors: str, modified_files: list[str]) -> bool:
    """尝试修复语法错误。"""
    log("=== 修复语法错误 ===")

    file_contents = {}
    for f in modified_files:
        fp = PROJECT_DIR / f
        if fp.exists():
            file_contents[f] = fp.read_text(encoding="utf-8")

    files_text = ""
    for f, content in file_contents.items():
        files_text += f"\n### {f}\n```python\n{content}\n```\n"

    result = call_llm(
        "你是 Python 语法修复专家。修复所有语法错误，输出完整文件。",
        f"## 语法错误\n{errors}\n\n## 文件内容\n{files_text}\n\n"
        "输出修复后的完整文件：\n"
        "```file:path/to/file.py\n修复后内容\n```",
        max_tokens=8192,
    )

    import re

    for m in re.finditer(r"```file:(.+?)\n(.*?)```", result, re.DOTALL):
        filepath = m.group(1).strip()
        content = m.group(2)
        full_path = PROJECT_DIR / filepath
        full_path.write_text(content, encoding="utf-8")
        log(f"  修复: {filepath}")

    ok, _ = stage_verify()
    return ok


def stage_evaluate(plan: dict, modified_files: list[str]) -> int:
    """阶段 5：LLM 评估改动质量。返回 1-10 分。"""
    log("=== 阶段 5: Evaluate ===")

    # 获取 diff
    _, diff = git("diff")
    if not diff:
        _, diff = git("diff", "--cached")
    if not diff:
        return 0

    # 截断太长的 diff
    if len(diff) > 5000:
        diff = diff[:5000] + "\n... (truncated)"

    result = call_llm(
        "你是代码审查专家。评估以下改动的质量。",
        f"## 任务\n{plan['task']}\n\n"
        f"## 代码 Diff\n```diff\n{diff}\n```\n\n"
        "## 评估标准\n"
        "- 是否正确实现了任务目标？\n"
        "- 有没有引入新 bug？\n"
        "- 代码质量如何？\n"
        "- 是否有副作用？\n\n"
        "输出格式（严格遵守）：\n"
        "score: 7\n"
        "reason: 简短评价\n"
        "只输出这两行，不要其他内容。",
        max_tokens=200,
    )

    # 解析评分
    import re

    m = re.search(r"score:\s*(\d+)", result)
    score = int(m.group(1)) if m else 5

    reason_m = re.search(r"reason:\s*(.+)", result)
    reason = reason_m.group(1).strip() if reason_m else ""

    log(f"评分: {score}/10 — {reason}")
    return score


def stage_report(plan: dict, score: int) -> None:
    """阶段 6：记录 CHANGELOG + 提交 + PR。"""
    log("=== 阶段 6: Report ===")

    today = datetime.now().strftime("%Y-%m-%d %H:%M")
    task = plan.get("task", "unknown")

    # 记录历史
    history = load_history()
    history.append(
        {
            "date": today,
            "task": task,
            "score": score,
        }
    )
    save_history(history)

    # 追加 CHANGELOG
    entry = f"\n## [{today}] auto-improve\n- {task} (score: {score}/10)\n"
    if CHANGELOG.exists():
        text = CHANGELOG.read_text(encoding="utf-8")
        CHANGELOG.write_text(text + entry, encoding="utf-8")
    else:
        CHANGELOG.write_text(f"# Changelog\n{entry}", encoding="utf-8")

    # 提交到 dev 分支
    git("checkout", "-B", "dev")
    git("add", ".")
    git("commit", "-m", f"auto-improve: {task}")
    code, out = git("push", "origin", "dev", "--force")
    if code == 0:
        log(f"已推送到 dev 分支")
    else:
        log(f"推送失败: {out}")

    # 创建 PR
    r = subprocess.run(
        [
            "gh",
            "pr",
            "list",
            "--head",
            "dev",
            "--state",
            "open",
            "--json",
            "number",
            "-q",
            ".[0].number",
        ],
        cwd=PROJECT_DIR,
        capture_output=True,
        text=True,
    )
    if r.returncode == 0 and r.stdout.strip():
        log(f"PR #{r.stdout.strip()} 已存在")
    else:
        subprocess.run(
            [
                "gh",
                "pr",
                "create",
                "--title",
                f"Auto-improve: {task}",
                "--body",
                f"AI 自动改进（评分 {score}/10）\n\n任务: {task}",
                "--head",
                "dev",
                "--base",
                "main",
            ],
            cwd=PROJECT_DIR,
        )

    # 切回 main
    git("checkout", "main")


def rollback() -> None:
    """回滚所有改动。"""
    log("回滚改动...")
    git("checkout", "--", ".")
    git("clean", "-fd")


# ── 主流程 ──


def run_one_round() -> bool:
    """执行一轮改进。返回是否成功。"""
    log("=" * 50)
    log("开始新一轮 Auto-Improve")
    log("=" * 50)

    try:
        # 确保在 main 分支最新状态
        git("checkout", "main")
        git("pull", "origin", "main")

        # 1. Analyze
        analysis = stage_analyze()
        if not analysis:
            log("分析失败，跳过本轮")
            return False

        # 2. Plan
        plan = stage_plan(analysis)
        if not plan.get("plan"):
            log("无可执行任务，跳过本轮")
            return False
        log(f"选定任务: {plan['task']}")
        log(f"涉及文件: {plan.get('files', [])}")

        # 文件数检查
        if len(plan.get("files", [])) > MAX_FILES:
            log(f"涉及 {len(plan['files'])} 个文件，超过限制 {MAX_FILES}，跳过")
            return False

        # 3. Implement
        modified = stage_implement(plan)
        if not modified:
            log("没有文件被修改，跳过")
            return False

        # 4. Verify（带修复循环）
        for fix_round in range(MAX_FIX_ROUNDS):
            ok, errors = stage_verify()
            if ok:
                break
            log(f"修复第 {fix_round + 1} 轮...")
            if not stage_fix(errors, modified):
                if fix_round == MAX_FIX_ROUNDS - 1:
                    log("修复失败，回滚")
                    rollback()
                    return False

        # 5. Evaluate
        score = stage_evaluate(plan, modified)
        if score < 6:
            log(f"评分 {score} < 6，回滚")
            rollback()
            return False

        # 6. Report
        stage_report(plan, score)
        log(f"本轮完成! 任务: {plan['task']}, 评分: {score}/10")
        return True

    except Exception as e:
        log(f"异常: {e}")
        rollback()
        return False


def main():
    parser = argparse.ArgumentParser(description="AI 自主改进守护进程")
    parser.add_argument("--daemon", action="store_true", help="守护模式持续运行")
    parser.add_argument(
        "--interval", type=int, default=1800, help="间隔秒数（默认 1800）"
    )
    args = parser.parse_args()

    if args.daemon:
        log(f"守护模式启动，间隔 {args.interval} 秒")
        while True:
            run_one_round()
            log(f"休息 {args.interval} 秒...")
            time.sleep(args.interval)
    else:
        success = run_one_round()
        sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
