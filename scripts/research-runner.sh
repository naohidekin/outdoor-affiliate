#!/bin/bash
#
# X投稿生成用リサーチスクリプトの一括ランナー。
# launchd から呼ばれる前提。kill-switch の researchEnabled=true なら各スクリプト側で exit する。
#
# 使い方:
#   ./scripts/research-runner.sh viral     # viral-scout-agent のみ（日次）
#   ./scripts/research-runner.sh weekly    # youtube + x-search（週次）
#   ./scripts/research-runner.sh all       # 全部

set -u

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
LOG_DIR="$PROJECT_DIR/logs"
mkdir -p "$LOG_DIR"

LOG_FILE="$LOG_DIR/research-$(date '+%Y%m%d').log"
NODE="${NODE:-/opt/homebrew/bin/node}"
MODE="${1:-viral}"

log() {
  echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*" | tee -a "$LOG_FILE"
}

cd "$PROJECT_DIR"

log "=== research-runner start (mode=$MODE) ==="

run_step() {
  local label="$1"
  shift
  log "--- $label 実行 ---"
  if "$NODE" "$@" >> "$LOG_FILE" 2>&1; then
    log "$label 完了"
  else
    log "$label 失敗 (exit=$?)"
  fi
}

case "$MODE" in
  viral)
    run_step "viral-scout-agent" scripts/viral-scout-agent.js --count=50 --min-score=50
    ;;
  weekly)
    run_step "youtube-researcher" scripts/youtube-researcher.js
    run_step "x-search" scripts/research-sources/x-search.js
    ;;
  all)
    run_step "viral-scout-agent" scripts/viral-scout-agent.js --count=50 --min-score=50
    run_step "youtube-researcher" scripts/youtube-researcher.js
    run_step "x-search" scripts/research-sources/x-search.js
    ;;
  *)
    log "不明なモード: $MODE"
    exit 1
    ;;
esac

log "=== research-runner 正常終了 ==="
