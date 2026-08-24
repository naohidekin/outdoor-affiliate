# Snow Peak IGT 英語MVP — 公開までの3作業

Claude側では実行できない3つを、コピペと選択だけで終わる形にまとめた。
所要はぜんぶで **40〜60分**。順番は 2 → 3 → 1 が効率的
（1がいちばん時間を食うので、先に器を用意しておく）。

作業環境: ご自宅のMac（`.env.local` があるマシン）。

---

## なぜClaudeがやれないのか

| 作業 | 理由 |
|---|---|
| 1. 公式データ投入 | 実行環境のegressゲートウェイが `www.snowpeak.co.jp` / `www.snowpeak.com` / `jp.snowpeak.com` を拒否（`connect_rejected`）。公式で裏が取れないものは入れない方針のため、検索結果の販売店ページで代用しない |
| 2. フォーム送信先 | `.env.local` はMacにのみ存在。Vercelの環境変数にもアクセス権がない |
| 3. GA4設定 | GA4管理画面へのアクセス権がない |

---

## 2. フォーム送信先（15分）

いちばん短い経路は **Google Apps Script + スプレッドシート**。
無料、アカウント追加なし、届いた内容がシートに溜まる。

### 手順

1. Googleドライブで新しいスプレッドシートを作る。名前は `IGT model requests` など
2. メニューの **拡張機能 → Apps Script** を開く
3. 中身を全部消して、下のコードを貼る

```javascript
// IGT model requests receiver
// Camp Gear Lab /en の Model Finder から POST を受けてシートに1行追記する
function doPost(e) {
  const sheet = SpreadsheetApp.getActiveSpreadsheet().getSheets()[0];

  // 初回だけ見出しを作る
  if (sheet.getLastRow() === 0) {
    sheet.appendRow([
      'submittedAt', 'modelNumber', 'productName',
      'market', 'purpose', 'email', 'source',
    ]);
  }

  let d = {};
  try {
    d = JSON.parse(e.postData.contents);
  } catch (err) {
    return ContentService
      .createTextOutput(JSON.stringify({ ok: false, error: 'bad json' }))
      .setMimeType(ContentService.MimeType.JSON);
  }

  sheet.appendRow([
    d.submittedAt || new Date().toISOString(),
    d.modelNumber || '',
    d.productName || '',
    d.market || '',
    d.purpose || '',
    d.email || '',
    d.source || '',
  ]);

  return ContentService
    .createTextOutput(JSON.stringify({ ok: true }))
    .setMimeType(ContentService.MimeType.JSON);
}
```

4. **デプロイ → 新しいデプロイ** → 種類は **ウェブアプリ**
   - 「次のユーザーとして実行」: **自分**
   - 「アクセスできるユーザー」: **全員**
     （サイトのサーバーから匿名でPOSTするため。読み出しの口は開かないので、
     書き込み専用として使える）
5. 出てくる `https://script.google.com/macros/s/AKfy.../exec` をコピー

### 設定する場所は2か所

**Mac の `.env.local`**（末尾に1行追記）

```
MODEL_REQUEST_FORM_URL=https://script.google.com/macros/s/AKfy.../exec
```

**Vercel**（本番に出すなら必須。ここを忘れると本番だけフォームが出ない）

Project → Settings → Environment Variables →
`MODEL_REQUEST_FORM_URL` を Production / Preview に追加 → 再デプロイ。

### 動作確認

```bash
npm run dev
# http://localhost:3000/en/tools/snow-peak-igt-model-finder/ を開く
# 適当な型番を検索 → 結果なし → フォームが出る → 送信
```

シートに1行増えれば成功。**フォームが出ない場合は環境変数が読めていない**
（`.env.local` を置いたあと dev サーバーを再起動する）。

### curl のレスポンスで成否を判断しない（2026-08-24 に踏んだ罠）

Apps Script の `/exec` は必ず **302** を返し、実行結果は
`script.googleusercontent.com/macros/echo?...` に置かれる。
`curl -L` で追うと元の `Content-Type: application/json` ヘッダーを
引き継いでしまい、Googleドライブの

```
現在、ファイルを開くことができません。
```

という **404ページが返る**。これは権限エラーにも実行エラーにも見えるが、
**どちらでもない**。書き込み自体は成功している。

実際この見た目に釣られて、権限設定とWorkspace制限を疑って2往復した。
どちらも正常だった。

**成否はシートを見て判断する。** レスポンス本文を見たいときは、
リダイレクト先を素のGETで取り直す。

```bash
LOC=$(curl -sS -o /dev/null -w '%{redirect_url}' -X POST "<URL>" \
  -H "Content-Type: application/json" -d '{"modelNumber":"TEST"}')
curl -sS "$LOC"
```

なお `/api/en/model-request` は Node の `fetch` を使っており、
リダイレクトは自動で追われる。これは curl 固有の引っかかり。

---

## 3. GA4カスタムディメンション（10分）

イベント自体は設定なしで飛ぶ。ただし**登録しないとGA4の画面で分解できない**。
「データは来ているのに読めない」状態になるので、データが溜まる前にやる。

GA4 → **管理 → データの表示 → カスタム定義 → カスタムディメンションを作成**

5つ登録する。範囲はすべて **イベント**。

| ディメンション名 | イベントパラメータ | 何を見るためか |
|---|---|---|
| Result status | `result_status` | 空振り率（need の強さ） |
| Model ID | `model_id` | どの型番が求められているか |
| Merchant | `merchant` | どの販売先が押されるか |
| Placement | `placement` | どの位置が効くか |
| Market | `market` | 米国か日本かその他か |

`page` は登録不要（`page_path` で足りる）。

### 注意

- **遡及しない。** 登録した日以降のデータにしか付かない
- カスタムディメンションは上限50。既存の登録数を確認してから追加する
- 反映に最大24時間かかる。すぐ見えなくても慌てない
- 確認は **レポート → リアルタイム** が速い。`/en/` を開いて
  `english_hub_view` / `finder_view` が立つか見る

### 探索レポートを1つ作っておくと後が楽

**探索 → 空白** で、ディメンションに `Result status`、指標に `イベント数`。
これで `result_found` と `result_unknown` の比が一目で出る。
この比が今回の一次指標になる。

---

## 1. 公式データ投入（20〜30分）

### 進め方

公式サイトを見ながら、**出典を先に、商品を後に**書く。
逆にすると存在しない出典IDを参照して検証に落ちる。

対象は5〜10件で十分。**多さより1件の正確さ**。
IGTフレーム本体とよく使うユニット/脚あたりが、質問が集中する領域のはず。

### 使ってよい情報源

- 公式商品ページ（snowpeak.co.jp / snowpeak.com）
- 公式マニュアル・取扱説明書PDF
- 公式アーカイブ（廃番品はこれが頼り）
- 公式サポート・お問い合わせ回答

**販売店・マーケットプレイス・掲示板・ショップブログは根拠にしない。**
`sourceType` の型が受け付けないので、間違えても検証で落ちる。

### 書き方

`data/experiments/snow-peak-igt/sources.json`

```json
[
  {
    "id": "sp-jp-<商品スラッグ>",
    "publisher": "Snow Peak Japan",
    "title": "<公式ページのタイトルをそのまま>",
    "url": "https://www.snowpeak.co.jp/...",
    "sourceType": "official_product_page",
    "lastVerifiedAt": "2026-08-24"
  }
]
```

`data/experiments/snow-peak-igt/products.json`

```json
[
  {
    "id": "igt-<短い識別子>",
    "productName": "<公式の表記そのまま>",
    "aliases": ["<略称>", "<旧表記>"],
    "japaneseModelNumber": "CK-xxx",
    "usModelNumber": null,
    "status": "current",
    "confirmedSuccessorId": null,
    "compatibility": [],
    "sourceIds": ["sp-jp-<商品スラッグ>"],
    "lastVerifiedAt": "2026-08-24",
    "purchaseOptions": [
      {
        "market": "us",
        "merchant": "Snow Peak USA",
        "url": "https://www.snowpeak.com/...",
        "affiliate": false
      }
    ]
  }
]
```

### 迷ったときの判断

| 状況 | どうするか |
|---|---|
| 米国型番が見つからない | `null` のまま。**日本型番をコピーしない** |
| 現行か廃番か分からない | `"unknown"`。憶測で `current` にしない |
| 後継品らしきものがある | 公式が後継と明記していなければ `null` |
| 後継品があるので互換だと思う | **`compatibility` に書かない。** 後継＝互換ではない |
| 互換だと公式に書いてある | `status: "confirmed"` ＋ その記述のある出典IDを必ず添える |
| 提携があるか曖昧 | `affiliate: false`。架空のIDは作らない |

**`affiliate: true` にするのは、その提携が現在有効だと確認できたときだけ。**
姉妹サイトの米国Amazonアカウントが2026-08-22に閉鎖された経緯があるので、
米国側リンクは特に慎重に。

### 検証

1件書くたびに回す（数秒で返る）。

```bash
npm run igt:check
```

- 必須条件を満たさなければ **exit 1** で理由を列挙する（ビルドも同じ判定で落ちる）
- 加えて、人が間違えやすい点を警告する
  （日米型番が同一 / 後継品ありで互換記録0件 / `affiliate: true` / 確認日が古い）
- 警告は落とさない。意図的ならそのままでよい

全部書き終えたら:

```bash
npm test && npm run build
```

---

## 仕上げ

```bash
git add -A
git commit -m "IGT: 公式資料で確認した本番データを投入"
git push -u origin claude/camp-gear-lab-review-n1n3e9
```

本番に出すなら `main` へマージ。マージ後、Search Console で
`https://camp-gear-lab.com/sitemap.xml` を再送信すると英語5URLの発見が早い。

### 公開後、最初に見る数字

| 指標 | 計算 | 読み方 |
|---|---|---|
| Finder利用率 | `finder_start` ÷ `finder_view` | 低ければ仮説が外れ |
| 空振り率 | `result_unknown` ÷ `finder_complete` | 高い＝データ不足だが**需要はある** |
| リクエスト率 | `model_request_submit` ÷ `result_unknown` | **最も強い需要シグナル** |

母数が溜まるまでは数字を動かしにいかないこと。
判断の詳細は `IMPLEMENTATION_REPORT.md` の §11 を参照。
