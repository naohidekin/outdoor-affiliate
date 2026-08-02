# SEO Indexing Runbook

camp-gear-lab.com の Google検索インデックス促進手順。GSC「検出 - インデックス未登録」が増えた時、新記事公開後、戦略的にクロール予算を消費したい時に使う。

## 仕組み

JSHで実証済みの2段構えアプローチを移植：

1. **Sitemap再送信** — Googleにサイトマップの再フェッチを促す
2. **Indexing API バッチping** — 個別URLを直接Googleにプッシュ通知

## 前提（既設定）

`.env.local` に以下が設定されている：

```
INDEXING_CREDENTIALS={"type":"service_account",...}
```

サービスアカウントは GSC で **「所有者」権限**を持っている必要がある。
権限不足の場合は https://search.google.com/search-console/users から追加。

> **やってはいけないこと**: `export $(grep '^INDEXING_CREDENTIALS' .env.local | xargs)`
> のような読み込みは実行しない。値がJSON（空白を含む）のため `xargs` が分解し、
> **bashのエラーメッセージとして秘密鍵の全文が画面に出力される**（2026-08-01に発生し、
> サービスアカウント鍵の再発行が必要になった）。
> 各スクリプトは自前で `.env.local` を読むので、環境変数を手で export する必要はない。
> そのまま `node scripts/request-indexing.js ...` を実行すればよい。

## 通常の運用フロー

### 新記事公開後

```bash
# 1. ローカルJSONとSupabaseの状態を同期（管理画面で公開した場合）
node scripts/sync-to-supabase.js

# 2. サイトマップ再送信
node scripts/resubmit-sitemap.js

# 3. Indexing API で全URLをping（クォータ200/日内）
node scripts/request-indexing.js
```

### 特定URLだけping

```bash
node scripts/request-indexing.js --urls https://camp-gear-lab.com/articles/foo
```

### 記事だけ／カテゴリだけ

```bash
node scripts/request-indexing.js --filter articles
node scripts/request-indexing.js --filter category
```

### 確認のみ（実行しない）

```bash
node scripts/request-indexing.js --dry-run
```

## 動作仕様

### `request-indexing.js`

- **URL取得**: `https://camp-gear-lab.com/sitemap.xml` をフェッチ + ローカル `data/articles.json` `data/categories.json` をマージ（和集合・重複除去）
  - ローカル優先で最新公開記事も漏れなく拾う
  - sitemap が CDN キャッシュされていても OK
- **レート制限**: 1.1秒/req（Indexing API 制限内）
- **クォータ**: デフォルト 200 req/day（`--limit` で調整）
- **ログ**: `data/seo-indexing-log.json` に成功/失敗を記録

### `resubmit-sitemap.js`

- GSC API で `https://camp-gear-lab.com/sitemap.xml` を再送信
- 送信前後の `lastSubmitted` と `contents` を表示

## トラブル対応

### 403 エラー

サービスアカウントが GSC「所有者」になっていない。
→ https://search.google.com/search-console/users で追加。

### 429 エラー（クォータ超過）

1日200URLが上限。`--limit` 指定するか、24時間後に再実行。
重要なURLから優先的に push する場合は `--filter articles` などで絞る。

### sitemap.xml に新記事が出ない

Vercel の CDN キャッシュ。sitemap は ISR でキャッシュされる。
1〜数分待つか、Vercel ダッシュボードから手動 redeploy。
ただし `request-indexing.js` はローカルJSONからもURLを拾うので、新記事は確実に ping される。

## GSC で結果確認

- インデックス状況: https://search.google.com/search-console
- 「ページ」レポートの「登録済み」「未登録」推移を1〜2週間追う
- 「検出 - インデックス未登録」が減れば成功

## 自動化（2026-04-27 追加）

管理画面（`/admin/articles`）から記事を**公開**する操作で、以下が自動連鎖実行されるようになった：

1. Supabaseに記事を published で保存
2. **Indexing API push**（個別URL）
3. **GSCサイトマップ再送信**
4. **ローカルJSONをSupabaseから自動pull**（ステイル防止）

実装箇所：
- `src/lib/indexing.ts` — `triggerPostPublishIndexing()` で2-3を統合
- `src/lib/local-sync.ts` — `pullFromSupabase()` で4を実装
- `src/app/api/articles/route.ts` — POST/PUTで公開時にfire-and-forget呼び出し

CLI側：
- `scripts/pull-from-supabase.js` — Supabase→ローカルJSON同期スクリプト
- `scripts/sync-to-supabase.js` — 起動時に上記を自動実行（`SKIP_AUTO_PULL=1` または `--no-pull` で無効化可）

→ **新記事公開後にCLIスクリプトを手動で叩く必要はなくなった**。
管理画面で公開すればすべて完了。

## 履歴

- 2026-04-27 11:42: JSHパターン移植、初回実行55 URL ping 全成功（クォータ55/200消費）
- 2026-04-27: 完全自動化（API route から triggerPostPublishIndexing + pullFromSupabase 連鎖）
