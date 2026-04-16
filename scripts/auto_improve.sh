#!/bin/bash
# auto-improve.sh — 用 OpenCode Agent 自主改进（带记忆和任务队列）
#
# 用法:
#   ./scripts/auto_improve.sh              # 运行一轮
#   ./scripts/auto_improve.sh --daemon     # 守护模式（24h）
#   ./scripts/auto_improve.sh --add "加批量处理功能"  # 添加任务到队列
#   ./scripts/auto_improve.sh --reject "原因"         # 记录拒绝（close PR 后执行）

set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
SCRIPTS_DIR="${PROJECT_DIR}/scripts"
LOG_FILE="${SCRIPTS_DIR}/.improve.log"
HISTORY_FILE="${SCRIPTS_DIR}/.improve-history.log"
REJECTED_FILE="${SCRIPTS_DIR}/.improve-rejected.log"
TODO_FILE="${SCRIPTS_DIR}/.improve-todo.md"
INTERVAL=1800
MAX_CHANGED_FILES=8

cd "$PROJECT_DIR"

log() {
    local msg="[$(date '+%Y-%m-%d %H:%M:%S')] $*"
    echo "$msg" | tee -a "$LOG_FILE"
}

# ── 任务队列管理 ──

add_todo() {
    local task="$1"
    echo "- [ ] $task" >> "$TODO_FILE"
    log "已添加任务: $task"
    echo "已添加到队列: $task"
    exit 0
}

mark_rejected() {
    local reason="$1"
    # 获取最近一条改进历史
    local last=$(tail -1 "$HISTORY_FILE" 2>/dev/null || echo "unknown")
    echo "[$(date '+%Y-%m-%d %H:%M')] REJECTED: $last | 原因: $reason" >> "$REJECTED_FILE"
    log "已记录拒绝: $reason"
    echo "已记录。下次不会再做类似的改进。"
    exit 0
}

# ── 检查被拒绝的 PR 并自动学习 ──

check_closed_prs() {
    if ! command -v gh &>/dev/null; then
        return
    fi

    # 获取最近关闭（非合并）的 PR
    local closed_prs=$(gh pr list --head dev --state closed --json number,title,mergedAt -q '.[] | select(.mergedAt == null) | .title' 2>/dev/null || echo "")
    if [ -n "$closed_prs" ]; then
        while IFS= read -r pr_title; do
            # 检查是否已记录
            if ! grep -q "$pr_title" "$REJECTED_FILE" 2>/dev/null; then
                echo "[$(date '+%Y-%m-%d %H:%M')] REJECTED (PR closed): $pr_title" >> "$REJECTED_FILE"
                log "检测到 PR 被关闭: $pr_title，已记录为拒绝"
            fi
        done <<< "$closed_prs"
    fi
}

# ── 完成任务队列中的项目 ──

complete_todo() {
    local task_keyword="$1"
    if [ -f "$TODO_FILE" ]; then
        # 把匹配的 [ ] 改成 [x]
        sed -i '' "/$task_keyword/s/\[ \]/[x]/" "$TODO_FILE" 2>/dev/null || \
        sed -i "/$task_keyword/s/\[ \]/[x]/" "$TODO_FILE" 2>/dev/null || true
    fi
}

# ── 核心执行 ──

run_one_round() {
    log "=========================================="
    log "开始新一轮 Auto-Improve"
    log "=========================================="

    # 检查被关闭的 PR（学习被拒绝的改进）
    check_closed_prs

    # 确保在 main 最新
    git checkout main 2>/dev/null || true
    git pull origin main 2>/dev/null || true

    # 创建 dev 分支
    git checkout -B dev origin/main 2>/dev/null || git checkout -B dev main 2>/dev/null || true

    # 调用 OpenCode Agent（macOS 没有 timeout，用兼容写法）
    log "调用 OpenCode Agent..."
    if command -v timeout &>/dev/null; then
        timeout 600 opencode run "/improve" 2>&1 | tee -a "$LOG_FILE"
    elif command -v gtimeout &>/dev/null; then
        gtimeout 600 opencode run "/improve" 2>&1 | tee -a "$LOG_FILE"
    else
        opencode run "/improve" 2>&1 | tee -a "$LOG_FILE"
    fi
    local opencode_exit=$?
    [ $opencode_exit -ne 0 ] && {
        log "OpenCode 执行失败或超时"
        git checkout main 2>/dev/null || true
        return 1
    }

    # 检查改动数量
    local changed=$(git diff --name-only | wc -l | tr -d ' ')
    local untracked=$(git ls-files --others --exclude-standard | wc -l | tr -d ' ')
    local total=$((changed + untracked))

    if [ "$total" -eq 0 ]; then
        log "没有改动"
        git checkout main 2>/dev/null || true
        return 0
    fi

    if [ "$total" -gt "$MAX_CHANGED_FILES" ]; then
        log "改动 $total 个文件，超过限制 $MAX_CHANGED_FILES，回滚"
        git checkout -- . 2>/dev/null || true
        git clean -fd 2>/dev/null || true
        git checkout main 2>/dev/null || true
        return 1
    fi

    # 语法检查
    log "语法检查..."
    local syntax_ok=true
    for f in $(find akasha -name '*.py'); do
        python3 -c "import ast; ast.parse(open('$f').read())" 2>/dev/null || {
            log "SyntaxError: $f"
            syntax_ok=false
        }
    done

    if [ "$syntax_ok" = false ]; then
        log "语法检查失败，回滚"
        git checkout -- . 2>/dev/null || true
        git clean -fd 2>/dev/null || true
        git checkout main 2>/dev/null || true
        return 1
    fi

    # 冒烟测试
    log "冒烟测试..."
    if command -v uv &>/dev/null; then
        uv run pytest tests/test_smoke.py -x -q 2>&1 | tee -a "$LOG_FILE" || {
            log "冒烟测试失败，回滚"
            git checkout -- . 2>/dev/null || true
            git clean -fd 2>/dev/null || true
            git checkout main 2>/dev/null || true
            return 1
        }
    else
        log "uv 不可用，跳过测试"
    fi

    # 提交
    git add .
    local diff_summary=$(git diff --cached --stat | tail -1 | sed 's/^ *//')
    local commit_msg="auto-improve: ${diff_summary}"
    git commit -m "$commit_msg" || {
        log "提交失败"
        git checkout main 2>/dev/null || true
        return 0
    }

    # 推送 dev
    git push origin dev --force 2>&1 | tee -a "$LOG_FILE" || {
        log "推送失败"
        git checkout main 2>/dev/null || true
        return 1
    }

    # 创建/更新 PR
    if command -v gh &>/dev/null; then
        local pr_num=$(gh pr list --head dev --state open --json number -q '.[0].number' 2>/dev/null || echo "")
        if [ -z "$pr_num" ]; then
            gh pr create \
                --title "Auto-improve $(date '+%m-%d %H:%M')" \
                --body "## AI 自动改进

改动: $total 个文件

\`\`\`
$(git diff HEAD~1 --stat)
\`\`\`

请 review 后合并。如需拒绝，close PR 后执行：
\`\`\`
./scripts/auto_improve.sh --reject \"拒绝原因\"
\`\`\`" \
                --head dev --base main 2>&1 | tee -a "$LOG_FILE" || true
            log "已创建 PR"
        else
            log "PR #$pr_num 已存在，已更新"
        fi
    fi

    # 记录历史
    echo "[$(date '+%Y-%m-%d %H:%M')] $commit_msg" >> "$HISTORY_FILE"

    git checkout main 2>/dev/null || true
    log "完成! 改动 $total 个文件"
    return 0
}

# ── 入口 ──

case "${1:-}" in
    --add)
        [ -z "${2:-}" ] && { echo "用法: $0 --add \"任务描述\""; exit 1; }
        add_todo "$2"
        ;;
    --reject)
        [ -z "${2:-}" ] && { echo "用法: $0 --reject \"拒绝原因\""; exit 1; }
        mark_rejected "$2"
        ;;
    --daemon)
        log "守护模式启动，间隔 ${INTERVAL}s"
        while true; do
            run_one_round || true
            log "休息 ${INTERVAL} 秒..."
            sleep "$INTERVAL"
        done
        ;;
    --history)
        cat "$HISTORY_FILE" 2>/dev/null || echo "（无历史）"
        ;;
    --status)
        echo "=== 任务队列 ==="
        cat "$TODO_FILE" 2>/dev/null || echo "（空）"
        echo ""
        echo "=== 最近改进 ==="
        tail -5 "$HISTORY_FILE" 2>/dev/null || echo "（无）"
        echo ""
        echo "=== 被拒绝 ==="
        tail -5 "$REJECTED_FILE" 2>/dev/null || echo "（无）"
        ;;
    *)
        run_one_round
        ;;
esac
