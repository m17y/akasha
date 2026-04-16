#!/bin/bash
# auto-improve.sh — 用 OpenCode Agent 自主改进
#
# 原理：调用 opencode CLI 的非交互模式，让它作为完整的 AI Agent
# 来分析项目、修改代码、验证、提交。OpenCode 有完整的工具链
# （读文件、写文件、执行命令、搜索代码），比自己写的 LLM 调用靠谱得多。
#
# 用法:
#   ./scripts/auto-improve.sh              # 运行一轮
#   ./scripts/auto-improve.sh --daemon     # 守护模式
#
# 前提:
#   1. 安装 opencode: npm install -g opencode-ai
#   2. 配置好 LLM provider（opencode 自带配置）
#   3. 项目根目录有 .opencode/commands/improve.md

set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
LOG_FILE="${PROJECT_DIR}/scripts/.improve.log"
HISTORY_FILE="${PROJECT_DIR}/scripts/.improve-history.log"
INTERVAL=1800  # 30 分钟
MAX_CHANGED_FILES=8

cd "$PROJECT_DIR"

log() {
    local msg="[$(date '+%Y-%m-%d %H:%M:%S')] $*"
    echo "$msg" | tee -a "$LOG_FILE"
}

run_one_round() {
    log "=========================================="
    log "开始新一轮 Auto-Improve"
    log "=========================================="

    # 确保在 main 最新
    git checkout main 2>/dev/null || true
    git pull origin main 2>/dev/null || true

    # 记录改动前的 hash
    local before_hash=$(git rev-parse HEAD)

    # 创建 dev 分支
    git checkout -B dev origin/main 2>/dev/null || git checkout -B dev main 2>/dev/null || true

    # 核心：用 opencode 的 /improve 命令
    # opencode 有完整的 Agent 能力：读文件、写文件、执行 bash、搜索代码
    log "调用 OpenCode Agent..."
    timeout 600 opencode -p "/improve 找出最有价值的改进点并实现。改完后执行语法检查：find akasha -name '*.py' -exec python3 -c \"import ast,sys; ast.parse(open(sys.argv[1]).read())\" {} \; 确保通过后再告诉我改了什么。" --yes 2>&1 | tee -a "$LOG_FILE" || {
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

    # 二次语法检查（防止 Agent 漏检）
    log "二次语法检查..."
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

    # 提交
    git add .
    local commit_msg="auto-improve: $(git diff --cached --stat | tail -1 | sed 's/^ *//')"
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
                --body "$(cat <<EOF
## AI 自动改进

改动文件: $total 个

### 改动内容
\`\`\`
$(git diff HEAD~1 --stat)
\`\`\`

请 review 后合并。
EOF
)" \
                --head dev --base main 2>&1 | tee -a "$LOG_FILE" || true
            log "已创建 PR"
        else
            log "PR #$pr_num 已存在，已更新"
        fi
    fi

    # 记录历史
    echo "[$(date '+%Y-%m-%d %H:%M')] $commit_msg (files: $total)" >> "$HISTORY_FILE"

    git checkout main 2>/dev/null || true
    log "完成! 改动 $total 个文件"
    return 0
}

# 主逻辑
if [ "${1:-}" = "--daemon" ]; then
    log "守护模式启动，间隔 ${INTERVAL}s"
    while true; do
        run_one_round || true
        log "休息 ${INTERVAL} 秒..."
        sleep "$INTERVAL"
    done
else
    run_one_round
fi
