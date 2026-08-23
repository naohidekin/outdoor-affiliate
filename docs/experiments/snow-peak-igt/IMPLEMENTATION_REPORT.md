# Snow Peak IGT 英語需要検証MVP — 実装報告

実装日: 2026-08-23 / ブランチ: `claude/camp-gear-lab-review-n1n3e9`
push・本番deployは行っていません。

---

## 1. 実装した内容

既存の `camp-gear-lab.com` 内に英語セクションを追加した。新ドメインもCMSも
DBも増やしていない。

| URL | 内容 | レンダリング |
|---|---|---|
| `/en/` | 英語セクション入口。4つの導線 | Static（1日） |
| `/en/tools/snow-peak-igt-model-finder/` | Model Finder | Dynamic |
| `/en/guides/snow-peak-igt-model-numbers/` | Guide 1本 | Static（1日） |
| `/en/methodology/` | 情報源と確認方法 | Static（1日） |
| `/en/affiliate-disclosure/` | 開示 | Static（1日） |

Finderだけ Dynamic なのは、`?q=` が付いたURLを noindex にするために
`searchParams` を読んでいるため（意図的）。

**Model Finder** は型番・商品名で検索し、日本型番／米国型番／状態／後継品／
公式に記載された互換性／出典／確認日／購入導線／注意点を表示する。
正規化で大文字小文字・ハイフン有無・空白有無・全角を吸収する。
判定表現は4つに限定し、推測・保証表現はコードで禁止している。

**未登録型番のリクエスト**は環境変数 `MODEL_REQUEST_FORM_URL` に送信先を
設定する方式。未設定なら壊れたフォームを出さず、案内文だけを表示する。

日本語フッターに控えめな `English` リンクを1本追加した。
**言語・IPによる強制リダイレクトは実装していない。**

---

## 2. 変更した主要ファイル

### 新規

```
data/experiments/snow-peak-igt/products.json      本番データ（空。理由は §6）
data/experiments/snow-peak-igt/sources.json       出典データ（空）
data/experiments/snow-peak-igt/README.md          データ追加時の条件

src/lib/experiments/snow-peak-igt/core.ts         型・正規化・検索・判定文言・検証
src/lib/experiments/snow-peak-igt/seo.ts          ページ定義・canonical・sitemap・robots
src/lib/experiments/snow-peak-igt/analytics.ts    イベント定義・payload sanitizer
src/lib/experiments/snow-peak-igt/data.server.ts  JSON読み込み＋検証

src/components/en/EnChrome.tsx                    英語ヘッダ・フッタ・インライン開示
src/components/en/EnClientBits.tsx                lang同期・表示計測・販売リンク
src/components/en/ModelFinder.tsx                 Finder本体
src/components/en/ModelRequest.tsx                未登録型番リクエスト

src/app/en/layout.tsx                             英語セクションの外枠
src/app/en/page.tsx
src/app/en/tools/snow-peak-igt-model-finder/page.tsx
src/app/en/guides/snow-peak-igt-model-numbers/page.tsx
src/app/en/methodology/page.tsx
src/app/en/affiliate-disclosure/page.tsx
src/app/api/en/model-request/route.ts             送信先への中継

tests/experiments/snow-peak-igt/fixtures.ts       テスト専用データ
tests/experiments/snow-peak-igt/search.test.ts
tests/experiments/snow-peak-igt/production-data.test.ts
tests/experiments/snow-peak-igt/seo.test.ts
tests/experiments/snow-peak-igt/analytics-and-markup.test.ts
```

### 既存への変更（最小限）

| ファイル | 変更 |
|---|---|
| `src/app/sitemap.ts` | 英語5URLを追加（`enSitemapEntries()` を連結） |
| `src/components/Footer.tsx` | 控えめな `English` リンクを1本 |
| `package.json` | `typecheck` / `test` / `verify` スクリプトを追加 |
| `tsconfig.json` | `allowImportingTsExtensions: true`（テストが `.ts` 拡張子付きでimportするため） |

既存のページ・ルーティング・ルートレイアウト・データ層には手を入れていない。

### ライブラリを3つに割った理由

テストを新規依存なしで回すため。`node --test` の型ストリップ実行は
拡張子省略のimportを解決できないので、`core.ts` / `seo.ts` / `analytics.ts` は
**他の `.ts` をランタイムimportしない**形にしてある。
`data.server.ts` だけが `./core` を読むが、これはNextのバンドラだけが解決し、
テストからは触らない。

---

## 3. 使用したデータと出典

**本番データは0件。空のまま実装した。**

作業環境のネットワークegressゲートウェイが Snow Peak 公式ドメインへの接続を
ポリシーで拒否していた。

```
www.snowpeak.co.jp:443  → gateway 403 (connect_rejected)
www.snowpeak.com:443    → gateway 403 (connect_rejected)
```

Web検索自体は通ったが、返ってくるのは Amazon・eBay・CampSaver などの
**販売店ページ**だった。これらは指示上、互換性の確定根拠にしてはいけない
情報源にあたる。公式ページで裏を取れない以上、投入すれば捏造になる。

そのため指示にある分岐どおり、**スキーマ・検証・空状態だけを実装した**。
Finderは「まだ公開している記録がない。推測で埋めるより空にしておく」と
明示し、リクエスト導線だけを出す。

テスト用fixtureは `tests/` 配下にあり、IDは全て `fixture-` 前置き、
URLは `example.invalid`。本番への混入はテストで検出する。

---

## 4. analyticsイベント一覧

既存のGA4（`G-0F2R4RX636`、ルートレイアウトで読み込み済み）を再利用。
新しい外部サービスは追加していない。

| イベント | 発火タイミング | 主な項目 |
|---|---|---|
| `english_hub_view` | `/en/` 表示 | `page` |
| `finder_view` | Finder表示 | `page` |
| `finder_start` | **最初の入力操作**（表示ではない） | `page` |
| `finder_complete` | 検索実行 | `page` |
| `result_found` | 該当あり | `page` `result_status` `model_id` |
| `result_unknown` | 該当なし | `page` `result_status` |
| `model_request_submit` | リクエスト送信成功 | `page` `market` |
| `affiliate_click` | 販売先クリック | `merchant` `market` `model_id` `placement` |

**載せてよい項目は6つだけ**（`page` `market` `model_id` `result_status`
`merchant` `placement`）。sanitizerが許可リスト外を落とすので、
自由入力・メールアドレス・氏名・完全なaffiliate URLは
「送らないよう気をつける」ではなく**送れない**。

`finder_start` を入力操作にしているのは、表示で発火させると `finder_view` と
同義になり「使われたか」が測れなくなるため。今回いちばん見たい指標がこれ。

---

## 5. lint / typecheck / test / build の実行結果

| 検査 | コマンド | 結果 |
|---|---|---|
| lint | `npm run lint` | **失敗（既存分のみ）** 96 problems / 36 errors |
| typecheck | `npm run typecheck` | **成功**（エラー0） |
| test | `npm test` | **成功** 75件すべて通過 |
| build | `npm run build` | **成功** exit 0 |

### lint について（正直に書く）

lintは通っていない。ただし**変更前と変更後で完全に同一**である。

```
変更前（git stash 状態）: ✖ 96 problems (36 errors, 60 warnings)
変更後:                   ✖ 96 problems (36 errors, 60 warnings)
```

内訳は `require()` 形式のimport 18件、`@ts-nocheck` 9件などで、
すべて既存の `.mjs` スクリプト群にある。**今回追加したファイルへの指摘は0件**
（`src/app/en` `src/components/en` `src/lib/experiments` `tests/` `api/en` を
grepして確認）。既存の指摘を今回まとめて直すのは範囲外と判断した。

### buildの確認

生成物まで見て確認した。

- 英語5ページすべて生成（4つStatic、Finderのみ Dynamic）
- `sitemap.xml` に英語5URLが載っている（`.next/server/app/sitemap.xml.body` で確認）
- `/en` のHTMLに `<link rel="canonical" href="https://camp-gear-lab.com/en"/>`
- `lang="en-US"` がSSR出力に存在
- `hreflang` は1つも生成されていない

---

## 6. 外部情報へアクセスできず未投入となったデータ

**商品データ全件と出典データ全件。**

投入予定だったが入れられなかったもの:

- IGT 各製品の日本型番・米国型番の対応
- 現行 / 廃番の別
- 廃番品の後継品
- 公式に記載された互換性（フレーム幅・ユニット数など）
- 出典URL（公式商品ページ・マニュアル・アーカイブ・サポート）
- 米国の購入導線

Web検索で `CK-080` / `CK-080R`（Entry IGT）などの型番は目にしたが、
公式ページで確認できていないため**あえて入れていない**。
「たぶん合っている値」を入れると、あとで検証済みの値と区別がつかなくなる。

---

## 7. 人間が追加すべき正式データ

公式サイトにアクセスできる環境（＝ふだんのMac）で作業してください。

1. `data/experiments/snow-peak-igt/sources.json` に出典を先に作る
   - `sourceType` は `official_product_page` / `official_manual` /
     `official_archive` / `official_support` のみ
   - `lastVerifiedAt` は**実際に見た日**。自動更新しない
2. `data/experiments/snow-peak-igt/products.json` に商品を作る
   - 5〜10件で十分。多さより1件の正確さ
   - 日本型番と米国型番を**混同しない**。片方しか分からなければ他方は `null`
   - `confirmedSuccessorId` と `compatibility` は**別に埋める**。
     後継品があるからといって互換性 `confirmed` にしない
   - 互換性を `confirmed` にするなら、その項目自身に `sourceIds` が要る
3. 検証は自動で走る。`npm test` と `npm run build` が落ちれば何かが足りない

判断に迷ったら埋めない。`null` のままにすれば表示側が `Unknown` /
`Insufficient evidence` に変換する。

---

## 8. フォーム送信先の設定方法

`.env.local`（および Vercel の環境変数）に1行:

```
MODEL_REQUEST_FORM_URL=https://<送信先>
```

- 送信先は **JSON の POST を受ける write-only なエンドポイント**
  （Google Apps Script のWebアプリ、Formspree、自前のWebhookなど）
- 受け取るJSON:
  `{ modelNumber, productName, market, purpose, email, submittedAt, source }`
- **未設定なら**フォームを描かず、案内文だけを出す（`/api/en/model-request` も
  503を返す）。入力させて捨てる事故を防ぐための二重の防御
- ブラウザには送信先URLを渡していない。`/api/en/model-request` が中継する
- 自由入力とメールアドレスは analytics にもサーバーログにも出していない

---

## 9. アフィリエイトリンクの設定方法

`products.json` の `purchaseOptions[]` に入れる。

```json
{ "market": "us", "merchant": "Snow Peak USA", "url": "https://...", "affiliate": false }
```

- `affiliate: true` → `rel="sponsored nofollow noopener noreferrer"`
- `affiliate: false` → `rel="nofollow noopener noreferrer"`（sponsoredを付けない）
- **正式なアフィリエイト契約やトラッキングIDが無いなら `affiliate: false` で
  通常のメーカーリンクとして扱う。** 架空のIDは作らない
- 最初の販売リンクより前にインライン開示が出る（テストで順序を検証）
- 価格・在庫・最安値・レビュー評価は表示していない（テストで混入を検出）

米国向けのAmazonアソシエイトは現在契約が無い。姉妹サイトの米国アカウントが
2026-08-22に閉鎖された経緯があるため、米国リンクを入れる場合は
**契約状態を確認してから**にしてください。

---

## 10. 本番公開前の確認事項

1. **`<html lang>` が `ja` のまま**（既知の限界）
   - SSR出力ではラッパー要素が `lang="en-US"`、`<html>` はJSで補正
   - 正しく直すにはルートレイアウトを route group で分割する必要があり、
     その場合 `app/not-found.tsx` が合成できなくなって
     `global-not-found`（experimental）が要る。MVPには重いので見送った
   - 英語セクションを続けるなら、この分割は早めに決めたほうがいい
2. データが空のまま公開するかどうか
   - 空でも「リクエストが来るか」は測れるが、Finderの価値は伝わりにくい
   - 5件でも入れてから公開するほうが、仮説の検証としては素直
3. `MODEL_REQUEST_FORM_URL` を設定したか（未設定ならリクエストが取れない＝
   検証指標の1つが欠ける）
4. GA4でカスタムディメンションを登録したか
   （`result_status` `model_id` `merchant` `placement` `market`。
   登録しないとGA4の画面で分解できない）
5. Search Console に `/en/` 配下が認識されるか（sitemap送信後）
6. `robots.txt` は `/api/` のみ Disallow。英語ページはクロール可能

---

## 11. 今回の需要検証で確認すべき指標

ページビューでは判断しない。**問題が実在するかどうか**を見る。

### 一次指標（仮説の核）

| 指標 | 計算 | 見方 |
|---|---|---|
| Finder利用率 | `finder_start` ÷ `finder_view` | 検索欄に触るか。**低ければ需要が無い** |
| 完了率 | `finder_complete` ÷ `finder_start` | 入力を最後までやるか |
| 空振り率 | `result_unknown` ÷ `finder_complete` | 高い＝データ不足。**需要はある証拠** |
| リクエスト率 | `model_request_submit` ÷ `result_unknown` | 空振りしてもなお知りたいか。**最も強い需要シグナル** |

### 二次指標（収益につながるか）

| 指標 | 計算 |
|---|---|
| 遷移率 | `affiliate_click` ÷ `result_found` |
| 市場別 | `affiliate_click` を `market` で分解 |
| 設置場所別 | `placement` で分解 |

### 読み方

- **`finder_start` が伸びない** → 仮説が外れ。撤退を検討
- **`result_unknown` が多く `model_request_submit` も多い** → 需要はある。
  データを足す価値がある。**このMVPが最も期待する状態**
- **`result_found` は出るが `affiliate_click` が出ない** →
  情報だけ取られて買われていない。収益化の設計を見直す
- **リクエストの型番に偏りがある** → そこから優先的にデータを埋める

判断できるだけの母数が集まるまでは、数字を動かしにいかないこと。
