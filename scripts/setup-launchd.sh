#!/bin/bash
#
# launchd plist のインストール / 再登録
#
# 使い方:
#   ./scripts/setup-launchd.sh           # 全 plist を登録
#   ./scripts/setup-launchd.sh --unload  # 全 plist を解除

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
PLIST_DIR="$PROJECT_DIR/launchd"
TARGET_DIR="$HOME/Library/LaunchAgents"

PLISTS=(
  "com.outdoor-affiliate.queue-to-sheets.plist"
  "com.outdoor-affiliate.sync-posted-status.plist"
  "com.outdoor-affiliate.nightly-analyst.plist"
  "com.outdoor-affiliate.weekly-pipeline.plist"
  "com.outdoor-affiliate.article-weekly.plist"
  "com.outdoor-affiliate.article-daily.plist"
)

if [ "${1:-}" = "--unload" ]; then
  echo "全 plist を解除します..."
  for plist in "${PLISTS[@]}"; do
    LABEL="${plist%.plist}"
    if launchctl list "$LABEL" &>/dev/null; then
      launchctl bootout "gui/$(id -u)/$LABEL" 2>/dev/null || launchctl unload "$TARGET_DIR/$plist" 2>/dev/null || true
      echo "  解除: $LABEL"
    else
      echo "  スキップ（未登録）: $LABEL"
    fi
  done
  echo "完了"
  exit 0
fi

echo "plist を $TARGET_DIR にコピー・登録します..."

for plist in "${PLISTS[@]}"; do
  LABEL="${plist%.plist}"
  SRC="$PLIST_DIR/$plist"

  if [ ! -f "$SRC" ]; then
    echo "  スキップ（ファイルなし）: $plist"
    continue
  fi

  # 既存を解除
  if launchctl list "$LABEL" &>/dev/null; then
    launchctl bootout "gui/$(id -u)/$LABEL" 2>/dev/null || launchctl unload "$TARGET_DIR/$plist" 2>/dev/null || true
  fi

  # コピー & 登録
  cp "$SRC" "$TARGET_DIR/$plist"
  launchctl bootstrap "gui/$(id -u)" "$TARGET_DIR/$plist" 2>/dev/null || launchctl load "$TARGET_DIR/$plist" 2>/dev/null
  echo "  登録: $LABEL"
done

echo ""
echo "登録済み:"
launchctl list | grep outdoor-affiliate || echo "  (なし)"
echo ""
echo "完了。ログ確認: ls $PROJECT_DIR/logs/"
