#!/bin/bash
#
# エラー通知ラッパー — 任意のコマンドを実行し、失敗時に macOS 通知 + エラーログを記録
#
# 使い方:
#   ./scripts/notify-on-error.sh "ジョブ名" コマンド [引数...]
#
# 例:
#   ./scripts/notify-on-error.sh "週次パイプライン" node scripts/orchestrate.js --pipeline weekly
#   ./scripts/notify-on-error.sh "キュー投入" bash scripts/cron-queue.sh

set -uo pipefail

LABEL="$1"
shift

# 通知は共通窓口へ送り、切替済みのSlack経路を使う。
# 実行コマンドの環境互換のため、既存の設定読込は維持する。
__TG_ENV_FILE="$HOME/.secretary/.env"
if [ -f "$__TG_ENV_FILE" ]; then
  set -a
  . "$__TG_ENV_FILE" 2>/dev/null || true
  set +a
fi
tg_notify() {
  bash "$HOME/.secretary/scripts/notify-owner.sh" "$1" "outdoor-link-check-failure"
}

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
LOG_DIR="$PROJECT_DIR/logs"
ERROR_LOG="$LOG_DIR/error-history.jsonl"
mkdir -p "$LOG_DIR"

# コマンド実行
"$@" 2>&1
EXIT_CODE=$?

if [ "$EXIT_CODE" -ne 0 ]; then
  TIMESTAMP=$(date -u +"%Y-%m-%dT%H:%M:%SZ")

  # macOS 通知
  osascript -e "display notification \"$LABEL が失敗しました (exit $EXIT_CODE)\" with title \"X自動化エラー\" sound name \"Basso\"" 2>/dev/null || true
  # 共通の監視キューへ配信
  tg_notify "🔗 [outdoor-affiliate] $LABEL が失敗しました (exit $EXIT_CODE)"

  # エラー履歴を JSONL で追記
  echo "{\"timestamp\":\"$TIMESTAMP\",\"label\":\"$LABEL\",\"exitCode\":$EXIT_CODE,\"command\":\"$*\"}" >> "$ERROR_LOG"

  echo "[notify] $LABEL 失敗 (exit $EXIT_CODE) — $TIMESTAMP"
fi

exit "$EXIT_CODE"
