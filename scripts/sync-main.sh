#!/bin/bash
# main反映ワンコマンド: npm run sync:main
# Supabaseミラーの掃除 → 作業ブランチのマージ → push → db:sync を安全に一括実行する。
# 途中で失敗したらそこで止まる（中途半端な状態でdb:syncが走る事故を防ぐ）。

set -e
cd "$(dirname "$0")/.."
BRANCH="origin/claude/camp-gear-lab-review-n1n3e9"

# 0. マージが途中なら人間の判断が必要なので停止
if [ -f .git/MERGE_HEAD ]; then
  echo "⚠️ マージが途中で止まっています。先に解消してください:"
  echo "   git merge --abort   （やり直す場合）"
  exit 1
fi

# 1. Supabaseミラー3ファイルの未コミット変更は捨てる
#    （db:syncのauto-pull書き戻しで汚れるだけ。真実はSupabaseとGitHubにある）
#    ※ data/kill-switch.json 等は対象外（誤って非常停止を解除しないため）
git checkout -- data/articles.json data/products.json data/categories.json 2>/dev/null || true

# 2. それ以外の未コミット変更があれば安全停止（何かを上書きしないため）
if ! git diff --quiet || ! git diff --cached --quiet; then
  echo "⚠️ ミラー以外に未コミットの変更があります。内容を確認してください:"
  git status --short
  exit 1
fi

# 3. 最新化してマージ → push
git fetch origin
git pull --no-edit origin main
git merge --no-edit "$BRANCH"
git push origin main

# 4. Supabaseへ反映（ここまで全部成功した時だけ実行される）
npm run db:sync

echo ""
echo "✅ main反映完了（GitHub → Vercelデプロイ → Supabase反映まで一気通貫）"
echo "   大量リライト後は追加で: npm run indexnow:all"
