#!/bin/bash
#
# Notion Poster セットアップ
#
# 使い方:
#   ./scripts/setup-notion-poster.sh
#
# やること:
#   1. NOTION_TOKEN が .env.local にあるか確認（なければ追記を案内）
#   2. launchd に notion-poster.plist を登録（setup-launchd.sh を再利用）
#   3. ドライランで動作確認

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
ENV_FILE="$PROJECT_DIR/.env.local"

echo "==============================="
echo " Notion Poster セットアップ"
echo "==============================="
echo ""

# ─── 1. NOTION_TOKEN チェック ─────────────────────────

if [ ! -f "$ENV_FILE" ]; then
  echo "❌ .env.local が見つかりません: $ENV_FILE"
  exit 1
fi

if grep -q "^NOTION_TOKEN=" "$ENV_FILE" && ! grep -q "^NOTION_TOKEN=$" "$ENV_FILE"; then
  echo "✅ NOTION_TOKEN: 設定済み"
else
  echo ""
  echo "⚠️  NOTION_TOKEN が未設定です。"
  echo ""
  echo "   Notion Integration Token を取得してください:"
  echo "   https://www.notion.so/my-integrations"
  echo ""
  echo "   取得後、.env.local に以下を追加:"
  echo "   NOTION_TOKEN=ntn_xxxxxxxxxxxxxxxxxxxxxxxxxxxx"
  echo "   ※ 新形式は ntn_、旧形式は secret_ で始まります"
  echo ""
  read -r -p "   今すぐ入力して追加しますか？ [y/N] " yn
  if [[ "${yn:-N}" =~ ^[Yy]$ ]]; then
    read -r -p "   NOTION_TOKEN の値: " notion_token
    if [[ "$notion_token" == secret_* ]] || [[ "$notion_token" == ntn* ]]; then
      echo "NOTION_TOKEN=$notion_token" >> "$ENV_FILE"
      echo "✅ .env.local に追記しました"
    else
      echo "❌ 値が 'ntn' または 'secret_' で始まっていません。手動で追加してください。"
      exit 1
    fi
  else
    echo "   後で手動で追加し、再度このスクリプトを実行してください。"
    exit 1
  fi
fi
echo ""

# ─── 2. マルチアカウントX認証 チェック ───────────────

echo "--- X 認証情報チェック ---"
check_x_creds() {
  local prefix="$1"
  local name="$2"
  local key="${prefix}X_API_KEY"
  if grep -q "^${key}=" "$ENV_FILE" && ! grep -q "^${key}=$" "$ENV_FILE"; then
    echo "  ✅ $name: 設定済み"
  else
    echo "  ⚠️  $name: 未設定 (${prefix}X_API_KEY / _SECRET / X_ACCESS_TOKEN / _SECRET)"
  fi
}
check_x_creds ""        "ギア男 (camp_gear_lab)"
check_x_creds "AMBLE_"  "アンブロ (san-pedinvestor)"
check_x_creds "LABO_"   "ラボ"
check_x_creds "KODOMO_" "こどもケアラボ"
check_x_creds "DROTO_"  "ドクターオート"
echo ""

# ─── 3. launchd 登録 ──────────────────────────────────

echo "--- launchd 登録 ---"
bash "$SCRIPT_DIR/setup-launchd.sh" 2>&1 | grep -E "登録:|スキップ|com.outdoor-affiliate.notion" || true
echo ""

# ─── 4. ドライラン ────────────────────────────────────

echo "--- ドライラン確認 ---"
cd "$PROJECT_DIR"
node scripts/notion-poster.js --dry-run
echo ""

echo "==============================="
echo " 完了！"
echo " Notionで「approved」にすると"
echo " 最大30分以内にXへ投稿されます"
echo "==============================="
