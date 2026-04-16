#!/bin/bash
# auto-improve.sh — AI 自主改进守护进程
#
# 24 小时不停运行，每轮：
# 1. 从 main 创建/更新 dev 分支
# 2. 让 AI 分析并改进代码
# 3. 语法检查
# 4. 提交到 dev 分支
# 5. 创建 PR（如果有改动）
# 6. 休息一段时间后继续
#
# 用法:
#   ./scripts/auto-improve.sh              # 前台运行
#   nohup ./scripts/auto-improve.sh &      # 后台运行
#   pm2 start scripts/auto-improve.sh      # 用 pm2 管理
#
# 安全机制:
# - 所有改动提交到 dev 分支，不直接推 main
# - 每轮语法检查，失败则回滚
# - 每轮最多改 5 个文件
# - 间隔 30 分钟，避免 API 滥用
# - 日志输出到 /tmp/akasha-improve.log

set -euo pipefail

PROJECT_DIR="${HOME}/work/git-hub/akasha"
LOG_FILE="/tmp/akasha-improve.log"
INTERVAL=1800  # 30 分钟
MAX_FILES=5

cd "$PROJECT_DIR"

log() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*" | tee -a "$LOG_FILE"
}

syntax_check() {
    log "语法检查..."
    local errors=0
    while IFS= read -r f; do
        python3 -c "import ast; ast.parse(open('$f').read())" 2>/dev/null || {
            log "SyntaxError: $f"
            errors=$((errors + 1))
        }
    done < <(find akasha -name '*.py')
    return $errors
}

run_improve() {
    log "========== 开始新一轮改进 =========="

    # 确保在最新的 main 上
    git checkout main 2>/dev/null
    git pull origin main 2>/dev/null || true

    # 创建/切换到 dev 分支
    git checkout -B dev origin/main 2>/dev/null || git checkout -B dev main

    # 记录改动前的状态
    local before_hash=$(git rev-parse HEAD)

    # 运行 AI 改进（用 opencode CLI 非交互模式）
    log "让 AI 分析并改进..."
    opencode -p "/improve" --yes 2>&1 | tee -a "$LOG_FILE" || {
        log "AI 改进执行失败，跳过本轮"
        git checkout main 2>/dev/null
        return 1
    }

    # 检查是否有改动
    local changed_files=$(git diff --name-only | wc -l)
    local untracked=$(git ls-files --others --exclude-standard | wc -l)
    local total=$((changed_files + untracked))

    if [ "$total" -eq 0 ]; then
        log "没有改动，跳过"
        git checkout main 2>/dev/null
        return 0
    fi

    if [ "$total" -gt "$MAX_FILES" ]; then
        log "改动文件数 $total 超过限制 $MAX_FILES，回滚"
        git checkout -- . 2>/dev/null
        git clean -fd 2>/dev/null
        git checkout main 2>/dev/null
        return 1
    fi

    # 语法检查
    if ! syntax_check; then
        log "语法检查失败，回滚"
        git checkout -- . 2>/dev/null
        git clean -fd 2>/dev/null
        git checkout main 2>/dev/null
        return 1
    fi

    # 提交到 dev
    git add .
    git commit -m "auto-improve: $(date '+%Y-%m-%d %H:%M')" || {
        log "没有需要提交的改动"
        git checkout main 2>/dev/null
        return 0
    }

    # 推送 dev 分支
    git push origin dev --force 2>&1 | tee -a "$LOG_FILE" || {
        log "推送失败"
        git checkout main 2>/dev/null
        return 1
    }

    # 创建 PR（如果不存在）
    if command -v gh &>/dev/null; then
        local existing_pr=$(gh pr list --head dev --state open --json number -q '.[0].number' 2>/dev/null)
        if [ -z "$existing_pr" ]; then
            gh pr create --title "Auto-improve $(date '+%m-%d')" \
                --body "AI 自动改进。请 review 后合并。" \
                --head dev --base main 2>&1 | tee -a "$LOG_FILE" || true
            log "已创建 PR"
        else
            log "PR #$existing_pr 已存在，已更新"
        fi
    fi

    git checkout main 2>/dev/null
    log "本轮完成，改动 $total 个文件"
    return 0
}

# 主循环
log "====== Auto-improve 守护进程启动 ======"
log "间隔: ${INTERVAL}s, 最大文件数: ${MAX_FILES}"
log "项目: ${PROJECT_DIR}"

while true; do
    run_improve || true
    log "休息 ${INTERVAL} 秒..."
    sleep "$INTERVAL"
done
