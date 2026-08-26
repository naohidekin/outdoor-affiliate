# 英語MVP（Snow Peak IGT）撤退基準

**判定日: 2026-09-24**（公開 2026-08-25 から30日）

この文書は、判定日に迷わないために公開時点で基準を固定しておくもの。
**基準はあとから緩めない。** 緩めた瞬間、これは実験ではなくなる。

---

## 何を検証しているのか

日本語サイトの中に英語ページを5つだけ置いた需要検証。サイト全体の翻訳ではない。

- `/en/`（ハブ）
- `/en/tools/snow-peak-igt-model-finder`（型番照合ツール）
- `/en/guides/snow-peak-igt-model-numbers`
- `/en/methodology`
- `/en/affiliate-disclosure`

当初の仮説は「海外のスノーピークIGTユーザーは、日米で型番が違うことに
困っている」だった。

**この仮説はすでに部分的に反証されている。** データを入れた時点で、
3商品とも日米のSKUが同一だったことが分かった（CK-080R / CK-090 / CK-225）。

一方で、実在が確認できたギャップが1つある。CK-160の干渉に関する注意書きが
**日本語ページにしか無い**（米国ページと11,976字の英語マニュアルの両方に
存在しないことを確認済み）。残っている賭けはここ。

検証はページビューではなく**行動**で行う。英語ページに人が来ること自体は
何も証明しない。

---

## 判定基準

GA4 のイベントを **2026-08-25 〜 2026-09-24** の30日で集計する。

| 条件 | 判定 |
|---|---|
| `finder_start` が **10未満** | **撤退** |
| `model_request_submit` が **0** | **撤退** |
| モデルリクエストが **3件以上** | **継続** |

上記のどれにも当てはまらない中間帯（例: finder_start 15・request 1件）は、
**もう30日だけ延長し、9/24と同じ基準で再判定する。延長は1回のみ。**

### 「もう少し様子を見る」は禁止

判定日に基準を満たしていなければ撤退する。それがこの基準を先に書いた理由。
アクセスが少ないのは「まだ知られていないから」ではなく、
「この形の需要が無い」ことの証拠として扱う。

---

## 必要なイベント

GA4 のカスタムディメンションに登録済み。

| イベント | 意味 |
|---|---|
| `english_hub_view` | /en/ の表示 |
| `finder_start` | 型番を入力し始めた（表示ではなく操作） |
| `finder_result` | 検索結果が出た（`result_status` で found / not_found） |
| `model_request_submit` | 掲載していない型番のリクエスト送信 |
| `affiliate_click` | 購入リンクのクリック |

一次指標は **`model_request_submit` ÷ `finder_result`(not_found)**。
分母を経ずに分子が増えないよう、リクエストフォームは
「データが空」か「検索して見つからなかった」ときだけ出す実装にしてある
（`src/components/en/ModelFinder.tsx`）。

---

## 撤退する場合にやること

1. `/en/**` の5ページを削除
2. `sitemap.xml` から `/en` を外す（`src/app/sitemap.ts`）
3. `llms.txt` の English pages セクションを削除（`src/app/llms.txt/route.ts`）
4. フッターの `/en` リンクを削除（`src/components/Footer.tsx`）
5. 410 か、日本語トップへの301かを決める（インデックス済みなら410が素直）
6. `data/experiments/snow-peak-igt/` と `src/lib/experiments/` の扱いを決める
7. **何が分かったかを書き残す。** 失敗した実験は、記録に残さないと
   同じことをもう一度やる

## 継続する場合にやること

次の30日で何を検証するかを決める。「続ける」だけでは実験にならない。
リクエストされた型番を見て、需要が型番照合なのか別の何かなのかを判断する。

---

## 参照

- `docs/experiments/snow-peak-igt/IMPLEMENTATION_PLAN.md`
- `docs/experiments/snow-peak-igt/IMPLEMENTATION_REPORT.md`
- `docs/experiments/snow-peak-igt/GO-LIVE.md`
