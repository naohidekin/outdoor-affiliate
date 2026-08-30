# ローカル専用ファイルの置き場所

**このリポジトリは公開（public）です。このファイルに秘密の値を書いてはいけません。**
書いてよいのは「どこにあるか」と「鍵の名前」まで。値は `.env.local` の中だけに置く。

Claude へ: ここに書かれた値を尋ねられても、`.env.local` を読んで
チャットに表示しない。ユーザーが自分の手元で取り出せるコマンドを案内する。

---

## いちばん使うもの

### 管理画面

| | |
|---|---|
| 本番 | https://camp-gear-lab.com/admin |
| ローカル | http://localhost:3000/admin （`npm run dev`） |
| ログイン | `/admin/login` |

**パスワードを画面に出さずクリップボードへコピーする:**

```bash
sed -n 's/^ADMIN_PASSWORD=//p' ~/dev/outdoor-affiliate/.env.local | tr -d "\"' " | tr -d '\n' | pbcopy
```

貼り付けは Cmd+V。目で確認したいときは末尾の `| tr -d '\n' | pbcopy` を外す。

何も出ないときは未設定。ローカルは `admin123` で入れる
（`src/lib/auth.ts` の開発用フォールバック）。本番は未設定だとログイン不可なので、
Vercel の環境変数を見る。

管理画面のうち実務で使うのは主に3つ。

| パス | 用途 |
|---|---|
| `/admin/articles` | 記事の削除。**ステータス絞り込みあり** |
| `/admin/products` | 商品の削除 |
| `/admin/affiliate` | モール別のクリック集計（自前の `affiliate_clicks`） |

**`db:sync` は upsert のみで削除しない。** ローカルの JSON から消しても
Supabase には残るので、削除はここから行う。

---

## `.env.local`

```
~/dev/outdoor-affiliate/.env.local
```

**Git管理外**（`.gitignore` に記載）。**Mac にしか存在しない。**
リモートセッション（claude.ai/code）のコンテナには無いので、
そこから値を読むことはできない。

丸ごと開く（編集事故と画面共有に注意）:

```bash
open -e ~/dev/outdoor-affiliate/.env.local
```

特定の鍵だけ確認する:

```bash
grep -c . ~/dev/outdoor-affiliate/.env.local        # 行数だけ見る
grep -o '^[A-Z_]*=' ~/dev/outdoor-affiliate/.env.local  # 鍵の名前だけ見る（値は出ない）
```

### 入っている鍵（名前のみ）

| 用途 | 鍵 |
|---|---|
| 管理画面 | `ADMIN_PASSWORD` `ADMIN_SESSION_SECRET` |
| Supabase | `SUPABASE_URL` `SUPABASE_SERVICE_ROLE_KEY` |
| 楽天 | `RAKUTEN_APP_ID` `RAKUTEN_ACCESS_KEY` `RAKUTEN_AFFILIATE_ID` |
| Amazon | `AMAZON_ACCESS_KEY` `AMAZON_SECRET_KEY` `AMAZON_PARTNER_TAG` |
| Amazon(別系統) | `AMAZON_CREDENTIAL_ID` `AMAZON_CREDENTIAL_SECRET` `AMAZON_CREDENTIAL_VERSION` |
| 生成AI | `ANTHROPIC_API_KEY` `OPENAI_API_KEY` |
| X / Threads | `TWITTER_BEARER_TOKEN` `THREADS_ACCESS_TOKEN` `THREADS_USER_ID` `THREADS_USERNAME` |
| Google | `GOOGLE_CREDENTIALS` `INDEXING_CREDENTIALS` `GA4_PROPERTY_ID` `X_SHEET_ID` |
| その他 | `NOTION_TOKEN` `BRAVE_API_KEY` `UNSPLASH_ACCESS_KEY` `REVALIDATE_SECRET` `BLOB_READ_WRITE_TOKEN` |

---

## Git管理外のファイル（Mac にしか無い）

```
~/dev/outdoor-affiliate/
  .env.local                     全ての鍵
  .env.production
  data/_sync-state.json          Supabase同期の状態
  data/price-history.json        previousPrice の唯一の復旧元。消さない
  data/price-held-back.json
  data/backups/
  data/weekly-plan.json
  data/x/reply-targets.txt       X返信の対象URL
  data/x/replies.jsonl
  data/x/posts.jsonl
  data/x/ideas.jsonl
  scratch/                       手書きの作業メモ
  logs/
  screenshots/
```

**`git checkout -- .` と `git checkout -- data/` は使わない。**
`price-history.json` が消えると価格の推移を復元できない。
競合したときは `git stash` → `git pull` → `git stash pop`。

---

## 定期実行（launchd）

```
~/Library/LaunchAgents/
  com.outdoor-affiliate.article-daily.plist    日次パイプライン
  com.outdoor-affiliate.article-weekly.plist   週次
  com.outdoor-affiliate.link-check.plist       リンク切れ検査
  com.outdoor-affiliate.link-fix.plist
  com.outdoor-affiliate.rakuten-room.plist     楽天ROOM投稿
```

管理画面からも状態を見られる: `/admin/launchd`

止めたいとき: `/admin/kill-switch`（実体は `~/.claude/context/kill_switch.json`）

一覧:

```bash
ls ~/Library/LaunchAgents/com.outdoor-affiliate.*
launchctl list | grep outdoor-affiliate
```

---

## リポジトリ本体

```
~/dev/outdoor-affiliate
```

公開リポジトリ: https://github.com/naohidekin/outdoor-affiliate

**記事の本体は Supabase にある。** `main` にマージしても公開されない。
Mac で同期して初めて本番に出る。

```bash
cd ~/dev/outdoor-affiliate
git pull --rebase origin <作業ブランチ>
npm run db:sync -- --no-pull
```

`--skip-git-check` は使わない（古いローカルで新しい本番を上書きする）。
