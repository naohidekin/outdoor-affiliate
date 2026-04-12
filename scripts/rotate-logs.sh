#!/bin/bash
#
# ログローテーション — 30日超のログファイルを削除
# 週次パイプラインの一部として、またはスタンドアロンで実行
#
# 使い方:
#   ./scripts/rotate-logs.sh            # 30日超を削除
#   ./scripts/rotate-logs.sh --days=60  # 60日超を削除
#   ./scripts/rotate-logs.sh --dry-run  # 削除対象を表示するのみ

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
LOG_DIR="$PROJECT_DIR/logs"
BACKUP_DIR="$PROJECT_DIR/data/backups"

DAYS=30
DRY_RUN=false

for arg in "$@"; do
  case "$arg" in
    --days=*) DAYS="${arg#*=}" ;;
    --dry-run) DRY_RUN=true ;;
  esac
done

echo "[rotate-logs] ${DAYS}日超の古いファイルを検索..."

DELETED=0

for DIR in "$LOG_DIR" "$BACKUP_DIR"; do
  if [ ! -d "$DIR" ]; then
    continue
  fi

  while IFS= read -r -d '' file; do
    if [ "$DRY_RUN" = true ]; then
      echo "  [DRY RUN] 削除対象: $(basename "$file") ($(stat -f '%Sm' -t '%Y-%m-%d' "$file"))"
    else
      rm -f "$file"
      echo "  削除: $(basename "$file")"
    fi
    DELETED=$((DELETED + 1))
  done < <(find "$DIR" -type f \( -name "*.log" -o -name "*.json" \) -mtime +"$DAYS" -print0 2>/dev/null)
done

# error-history.jsonl が 1000行超の場合、直近500行に truncate
ERROR_LOG="$LOG_DIR/error-history.jsonl"
if [ -f "$ERROR_LOG" ]; then
  LINE_COUNT=$(wc -l < "$ERROR_LOG")
  if [ "$LINE_COUNT" -gt 1000 ]; then
    if [ "$DRY_RUN" = true ]; then
      echo "  [DRY RUN] error-history.jsonl: ${LINE_COUNT}行 → 500行に truncate"
    else
      tail -500 "$ERROR_LOG" > "${ERROR_LOG}.tmp" && mv "${ERROR_LOG}.tmp" "$ERROR_LOG"
      echo "  error-history.jsonl: ${LINE_COUNT}行 → 500行に truncate"
    fi
  fi
fi

if [ "$DELETED" -eq 0 ]; then
  echo "[rotate-logs] 削除対象なし"
else
  echo "[rotate-logs] ${DELETED}ファイル処理完了"
fi
