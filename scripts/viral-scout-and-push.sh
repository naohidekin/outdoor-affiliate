#!/bin/bash
# viral-scout 実行 → git push → Vercel デプロイ を一気通貫で行う

set -e

REPO="/Users/NaohideKin/Desktop/AI関連/claude/outdoor-affiliate"
NODE="/opt/homebrew/bin/node"
GIT="/usr/bin/git"
LOG_PREFIX="[viral-scout-and-push]"

echo "$LOG_PREFIX 開始: $(date '+%Y-%m-%d %H:%M:%S')"

# 1. viral-scout 実行
echo "$LOG_PREFIX viral-scout 実行中..."
cd "$REPO"
"$NODE" scripts/viral-scout-agent.js --days=1 --count=50 --min-score=50
echo "$LOG_PREFIX viral-scout 完了"

# 2. git push（data/viral-scout-results.json を Vercel に反映）
echo "$LOG_PREFIX git push 中..."
cd "$REPO"

# 変更があるファイルのみコミット
if "$GIT" diff --quiet data/viral-scout-results.json data/buzz-first-lines.json 2>/dev/null; then
  echo "$LOG_PREFIX 変更なし、push スキップ"
else
  "$GIT" add data/viral-scout-results.json data/buzz-first-lines.json 2>/dev/null || true
  "$GIT" commit -m "chore: auto update viral-scout results $(date '+%Y-%m-%d')" \
    --author="launchd <launchd@localhost>"
  "$GIT" push origin HEAD
  echo "$LOG_PREFIX git push 完了 → Vercel が自動デプロイ開始（約1-2分）"
fi

echo "$LOG_PREFIX 全工程完了: $(date '+%Y-%m-%d %H:%M:%S')"
