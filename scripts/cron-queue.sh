#!/bin/bash
#
# queue-to-sheets.js のラッパースクリプト（launchd用）
# 曜日+祝日判定を行い、該当スロットのみ node を実行する
#
# launchd トリガー:
#   08:00 → 平日かつ非祝日のみ実行
#   10:00 → 土日 or 祝日のみ実行
#   19:00 → 毎日実行
#
# 使い方（手動テスト）:
#   ./scripts/cron-queue.sh          # 現在時刻で判定
#   FORCE_SLOT=morning ./scripts/cron-queue.sh  # 朝スロット強制実行

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
LOG_DIR="$PROJECT_DIR/logs"
mkdir -p "$LOG_DIR"

LOG_FILE="$LOG_DIR/cron-queue-$(date +%Y%m%d).log"

log() {
  echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*" | tee -a "$LOG_FILE"
}

# 祝日判定
HOLIDAYS_FILE="$PROJECT_DIR/data/jp-holidays.json"
TODAY=$(date +%Y-%m-%d)
YEAR=$(date +%Y)
DOW=$(date +%u)  # 1=月 ... 7=日

is_holiday() {
  if [ -f "$HOLIDAYS_FILE" ]; then
    grep -q "\"$TODAY\"" "$HOLIDAYS_FILE" && return 0
  fi
  return 1
}

is_weekend() {
  [ "$DOW" -eq 6 ] || [ "$DOW" -eq 7 ]
}

is_off_day() {
  is_weekend || is_holiday
}

# 現在の時刻からスロットを判定
HOUR=$(date +%H)
if [ -n "${FORCE_SLOT:-}" ]; then
  SLOT="$FORCE_SLOT"
elif [ "$HOUR" -lt 9 ]; then
  SLOT="morning_weekday"  # 08:00 トリガー
elif [ "$HOUR" -lt 12 ]; then
  SLOT="morning_holiday"  # 10:00 トリガー
else
  SLOT="evening"          # 19:00 トリガー
fi

log "スロット判定: SLOT=$SLOT DOW=$DOW TODAY=$TODAY"

# スロット判定
case "$SLOT" in
  morning_weekday)
    if is_off_day; then
      log "土日祝のため朝08:00スロットをスキップ"
      exit 0
    fi
    log "平日朝スロット実行"
    ;;
  morning_holiday)
    if ! is_off_day; then
      log "平日のため朝10:00スロットをスキップ"
      exit 0
    fi
    log "休日朝スロット実行"
    ;;
  morning)
    log "朝スロット強制実行"
    ;;
  evening)
    log "夜スロット実行"
    ;;
  *)
    log "不明なスロット: $SLOT"
    exit 1
    ;;
esac

# Node.js パス（launchd は PATH が最小限のため明示指定）
NODE_PATH="${NODE_PATH:-$(which node)}"

cd "$PROJECT_DIR"

# Step 1: 承認済み投稿をキューに投入
log "queue-to-sheets.js 実行開始（--max=1 --random-delay=59）"
"$NODE_PATH" scripts/queue-to-sheets.js --max=1 --random-delay=59 2>&1 | tee -a "$LOG_FILE"
QUEUE_EXIT=${PIPESTATUS[0]}

if [ "$QUEUE_EXIT" -ne 0 ]; then
  log "queue-to-sheets.js エラー終了 (exit=$QUEUE_EXIT)"
  exit "$QUEUE_EXIT"
fi

# Step 2: ready の投稿を X API で投稿
log "post-to-x.js 実行開始（--max=1）"
"$NODE_PATH" scripts/post-to-x.js --max=1 2>&1 | tee -a "$LOG_FILE"
POST_EXIT=${PIPESTATUS[0]}

if [ "$POST_EXIT" -eq 0 ]; then
  log "正常完了"
else
  log "post-to-x.js エラー終了 (exit=$POST_EXIT)"
fi

exit "$POST_EXIT"
