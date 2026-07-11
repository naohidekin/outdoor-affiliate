#!/bin/bash
#
# launchd plist のインストール / 再登録 / 退役ジョブの掃除
# plist内のパス（/Users/USERNAME/... プレースホルダ含む）を現在のマシンに
# 自動置換してからコピーする。
#
# 2026-07-11 棚卸監査による再設計:
#   生かす5本 = notion-poster / article-daily / article-weekly(下書き止まり改造済み)
#               / gearman-reply-fill / link-check
#   保留      = price-monitor（PA-APIキー等の3条件が揃ったら PLISTS へ戻す）
#   退役8本   = launchd/retired/ 参照。実行のたびに自動アンロード＆撤去する
#   詳細は docs/automation-map.md
#
# 使い方:
#   ./scripts/setup-launchd.sh           # 生かす分を登録 + 退役分を掃除
#   ./scripts/setup-launchd.sh --unload  # 生かす分も含め全て解除

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
PLIST_DIR="$PROJECT_DIR/launchd"
TARGET_DIR="$HOME/Library/LaunchAgents"

# 現在のマシンのパスを検出
if command -v nvm &>/dev/null || [ -d "$HOME/.nvm" ]; then
  CURRENT_NODE="$(which node)"
  NVM_NODE_DIR="$(dirname "$CURRENT_NODE")"
  CURRENT_PATH="$NVM_NODE_DIR:/usr/local/bin:/opt/homebrew/bin:/usr/bin:/bin"
else
  CURRENT_NODE="$(which node)"
  CURRENT_PATH="/usr/local/bin:/opt/homebrew/bin:/usr/bin:/bin"
fi

echo "検出パス:"
echo "  PROJECT: $PROJECT_DIR"
echo "  NODE:    $CURRENT_NODE"
echo "  PATH:    $CURRENT_PATH"
echo ""

# ─── 生かすジョブ ───────────────────────────────
PLISTS=(
  "com.outdoor-affiliate.notion-poster.plist"
  "com.outdoor-affiliate.article-daily.plist"
  "com.outdoor-affiliate.article-weekly.plist"
  "com.outdoor-affiliate.gearman-reply-fill.plist"
  "com.outdoor-affiliate.link-check.plist"
)

# ─── 退役・保留ジョブ（毎回アンロード＆LaunchAgentsから撤去） ───
RETIRED_LABELS=(
  "com.outdoor-affiliate.queue-to-sheets"
  "com.outdoor-affiliate.sync-posted-status"
  "com.outdoor-affiliate.nightly-analyst"
  "com.outdoor-affiliate.weekly-pipeline"
  "com.outdoor-affiliate.analyze-x"
  "com.outdoor-affiliate.x-trend-researcher"
  "com.outdoor-affiliate.threads-poster"
  "com.outdoor-affiliate.price-monitor"   # 保留: PA-API条件が揃ったらPLISTSへ
)

unload_label() {
  local LABEL="$1"
  if launchctl list "$LABEL" &>/dev/null; then
    launchctl bootout "gui/$(id -u)/$LABEL" 2>/dev/null || launchctl unload "$TARGET_DIR/$LABEL.plist" 2>/dev/null || true
    echo "  解除: $LABEL"
  fi
  if [ -f "$TARGET_DIR/$LABEL.plist" ]; then
    rm -f "$TARGET_DIR/$LABEL.plist"
    echo "  撤去: $TARGET_DIR/$LABEL.plist"
  fi
}

if [ "${1:-}" = "--unload" ]; then
  echo "全 plist を解除します..."
  for plist in "${PLISTS[@]}"; do unload_label "${plist%.plist}"; done
  for label in "${RETIRED_LABELS[@]}"; do unload_label "$label"; done
  echo "完了"
  exit 0
fi

echo "① 退役ジョブを掃除します..."
for label in "${RETIRED_LABELS[@]}"; do unload_label "$label"; done

echo ""
echo "② 生かすジョブを $TARGET_DIR に登録します..."
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

  # パスを現在のマシンに置換してコピー
  sed \
    -e "s|/opt/homebrew/bin/node|$CURRENT_NODE|g" \
    -e "s|/Users/[^<]*/outdoor-affiliate|$PROJECT_DIR|g" \
    -e "s|/usr/local/bin:/opt/homebrew/bin:/usr/bin:/bin|$CURRENT_PATH|g" \
    "$SRC" > "$TARGET_DIR/$plist"

  if launchctl bootstrap "gui/$(id -u)" "$TARGET_DIR/$plist" 2>/dev/null || launchctl load "$TARGET_DIR/$plist" 2>/dev/null; then
    echo "  登録: $LABEL"
  else
    echo "  ⚠️ 登録失敗: $LABEL（bootstrap/load とも失敗。launchctl bootout gui/\$(id -u)/$LABEL 後に再実行してください）"
  fi
done

mkdir -p "$PROJECT_DIR/logs"

echo ""
echo "登録済み:"
launchctl list | grep outdoor-affiliate || echo "  (なし)"
echo ""
echo "完了。ログ確認: ls $PROJECT_DIR/logs/"
echo "※ notion-poster 復旧後は、停止中に溜まった Notion の approved ページを一度棚卸ししてください"
