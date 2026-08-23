# Snow Peak IGT 英語需要検証MVP — 実装計画

作成: 2026-08-23

## 検証したい仮説

英語圏の Snow Peak IGT ユーザーには、日本型番・米国型番・廃番品・後継品・互換性を
確認したい需要があり、それを解決すると販売先への遷移につながる。

計測対象はページビューではなく **Finderの利用 / 未登録型番のリクエスト / 販売先クリック**。

## 調査で分かった既存構成（この計画の前提）

| 項目 | 実態 |
|---|---|
| フレームワーク | Next.js 16.2.1 App Router（`next build --webpack`） |
| ルートレイアウト | `src/app/layout.tsx` 1つ。`<html lang="ja">` 固定 |
| analytics | GA4 gtag（`G-0F2R4RX636`）をルートレイアウトで読み込み済み |
| クリック計測 | `src/lib/trackAffiliateClick.ts` → GA4 + `/api/track-click` ビーコン |
| アフィリエイトrel | `AffiliateLink.tsx` が `noopener noreferrer nofollow sponsored` |
| デザイン | Tailwind v4 + `globals.css` のトークン（lake/ink/snow/line）、`.prose` |
| sitemap | `src/app/sitemap.ts`（Supabaseから記事取得、`revalidate = 21600`） |
| robots | `/api/` のみ Disallow |
| フォーム機構 | **存在しない**。問い合わせはXのDM誘導のみ |
| テスト基盤 | **存在しない**。`lint` と `build` のみ |
| Node | v22.22.2（型ストリップ対応 → `node --test` が新規依存なしで使える） |

## 判断が必要だった2点

### 1. `lang="en-US"` をどう出すか

Next.js で `<html lang>` を出し分けるには、ルートレイアウトを複数持つ
（route group で分割する）必要がある。同梱ドキュメント
`node_modules/next/dist/docs/01-app/03-api-reference/03-file-conventions/not-found.md`
によると、ルートレイアウトを複数にした場合、現行の `app/not-found.tsx` は
合成できなくなり **`global-not-found.js`（experimental）** が要る。

既存の全ページを route group へ移動し、さらに実験的機能を有効化するのは
MVPに対して重すぎ、「全面的なリファクタリングを行わない」という条件にも反する。

**採る方法**: `/en` 配下のラッパー要素に `lang="en-US"` を付ける（SSR出力に含まれる）。
加えて小さなクライアントコンポーネントで `document.documentElement.lang` を
`en-US` に同期する。`<html>` の初期値が `ja` のまま残る点は既知の限界として
報告書に明記し、正しい直し方（ルートレイアウト分割）も併記する。

### 2. 本番データを入れられるか

**入れられない。** このコンテナのegressゲートウェイが Snow Peak 公式ドメインを
ポリシーで拒否している（`connect_rejected` / gateway 403）。

```
www.snowpeak.co.jp:443  → 403 CONNECT 拒否
www.snowpeak.com:443    → 403 CONNECT 拒否
```

Web検索自体は通るが、返るのは Amazon・eBay・CampSaver 等の**販売店ページ**で、
これらは指示上「互換性の確定根拠にしてはいけない」情報源にあたる。
公式ページで裏を取れない以上、投入すれば捏造になる。

**採る方法**: 指示にある分岐どおり、本番データは**空**のまま、
スキーマ・検証・空状態を実装する。テスト用fixtureは本番と完全に分離し、
混入しないことをテストで守る。人間が追加すべき内容は報告書に列挙する。

## 実装するもの

### データ

```
data/experiments/snow-peak-igt/products.json   → []（空。捏造しない）
data/experiments/snow-peak-igt/sources.json    → []
```

型は指示のとおり `ProductRecord` / `SourceRecord`。
`Current` / `Discontinued` / `Successor` / `Compatible` は別概念として保持し、
後継品の存在から互換性を自動導出しない。

### ライブラリ

テストを新規依存なしで回すため、**ランタイムのcross-import を持たない**単位に割る
（`node --test` の解決規則は拡張子省略を許さないため）。

| ファイル | 中身 | ランタイムimport |
|---|---|---|
| `src/lib/experiments/snow-peak-igt/core.ts` | 型・正規化・検索・判定文言・バリデーション | なし |
| `src/lib/experiments/snow-peak-igt/seo.ts` | 英語ページ一覧・canonical・sitemapエントリ・Finderのrobots | なし（型のみ） |
| `src/lib/experiments/snow-peak-igt/analytics.ts` | イベント名・payload sanitizer・送信 | なし |
| `src/lib/experiments/snow-peak-igt/data.server.ts` | JSON読み込み＋検証（サーバー専用） | `./core`（Nextのみが解決） |

正規化は大文字小文字・ハイフン有無・空白有無・全角半角（NFKC）を吸収する。

判定文言は次の4つに限定し、推測・保証表現は出さない。

```
Confirmed by official documentation
Current equivalent identified
Discontinued — no confirmed successor
Insufficient evidence
```

欠損は空文字や0ではなく `Unknown` / `Insufficient evidence` を表示する。

### ページ

```
/en/                                        英語セクション入口
/en/tools/snow-peak-igt-model-finder/       Model Finder
/en/guides/snow-peak-igt-model-numbers/     Guide 1本
/en/methodology/                            情報源と確認方法
/en/affiliate-disclosure/                   開示
```

日本語フッターに控えめな `English` リンクを1本追加する。
**言語・IPによる強制リダイレクトは実装しない。**

### 未登録型番リクエスト

既存にフォーム保存機構がないため、環境変数 `MODEL_REQUEST_FORM_URL` に
外部フォームURLを設定する方式にする。未設定なら壊れたフォームを出さず、
案内文だけを表示して導線を無効化する。
自由入力とメールアドレスは analytics へ送らない。

### analytics

既存のGA4 gtagを再利用する。イベントは8種。

```
english_hub_view / finder_view / finder_start / finder_complete
result_found / result_unknown / model_request_submit / affiliate_click
```

送ってよいのは `page / market / model_id / result_status / merchant / placement` のみ。
sanitizer で許可リスト外のキーを落とす。`link_url` は既存JP実装では送っているが、
英語側では「完全なaffiliate URLを含めない」条件があるため送らない。
`finder_start` は表示ではなく**最初の入力操作**で1回だけ発火させる。

### SEO

- 各ページに英語 title/description、自己参照canonical
- sitemap に5URLを追加（`enSitemapEntries()` を `src/app/sitemap.ts` から呼ぶ）
- 日本語版が無いので **hreflang は生成しない**
- Finderの検索結果は同一ページ内で表示。型番ごとのURLを作らない。
  `?q=` が付いた場合は `robots: noindex` を返す

## テスト

`node --test`（Node 22の型ストリップ）。新規依存なし。

- 型番の完全一致 / 大文字小文字 / ハイフン有無 / 空白有無 / 商品名・alias
- Current / Discontinued / Successor / Unknown の各表示
- source が無い本番データを拒否する
- lastVerifiedAt が無い本番データを拒否する
- affiliate link の `rel`
- analytics payload に自由入力・メールアドレスが入らない
- 英語ページの canonical / `lang`
- sitemap への登録
- hreflang を生成しない
- 検索結果URLが大量にindexableにならない
- fixture が本番データに混入しない

## 完了条件

`package.json` に `typecheck` / `test` / `verify` を追加し、次を実行する。

```
npm run lint
npm run typecheck
npm test
npm run build
```

## やらないこと（指示どおり）

日本語サイトの英訳、英語記事の量産、CMS・管理画面・認証・DB追加、Supabase新規導入、
汎用IGTコンフィギュレーター、商品ごとの自動生成ページ、検索語ごとのindexable URL、
価格・在庫追跡、Amazonのスクレイピング、ガス・燃料・火器改造の互換性判定、
公式で確認できない社外製品の適合保証。

remoteへのpushと本番deployも行わない。
