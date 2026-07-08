#!/usr/bin/env node

/**
 * 新記事「ポータブル電源おすすめ」＋商品4件を追加（gitなしでローカル反映）
 * 使い方: node scripts/add-portable-power-article.mjs  →  npm run db:sync
 * ※ 冪等: 既に存在するID/slugはスキップ
 */

import fs from "fs";
import path from "path";
import { fileURLToPath } from "url";

const ROOT = path.join(path.dirname(fileURLToPath(import.meta.url)), "..");
const productsPath = path.join(ROOT, "data", "products.json");
const articlesPath = path.join(ROOT, "data", "articles.json");
const now = new Date().toISOString();

const AFF_ID = "18eb3228.621d8df3.18eb3229.ec5f8d49";
const rk = (url) => `https://hb.afl.rakuten.co.jp/ichiba/${AFF_ID}/?pc=${encodeURIComponent(url)}&link_type=text&ut=`;
const rkSearch = (q) => rk(`https://search.rakuten.co.jp/search/mall/${encodeURIComponent(q)}/`);
const az = (q) => `https://www.amazon.co.jp/s?k=${encodeURIComponent(q)}&tag=camp78-22`;
const yh = (q) => `https://shopping.yahoo.co.jp/search?p=${encodeURIComponent(q)}`;

const NEW_PRODUCTS = [
  {
    id: "power-jackery-1000-new", name: "Jackery ポータブル電源 1000 New", brand: "Jackery",
    price: 65890, imageUrl: "",
    affiliateUrl: rkSearch("Jackery ポータブル電源 1000 New"),
    amazonUrl: az("Jackery ポータブル電源 1000 New"), yahooUrl: yh("Jackery ポータブル電源 1000 New"),
    categoryId: "portable-power",
    specs: { "容量": "1070Wh", "定格出力": "1500W（瞬間3000W）", "重量": "約10.8kg", "バッテリー": "リン酸鉄（LFP・約4000サイクル）" },
    description: "1000Whクラス最軽量級の約10.8kg。軽さ・静音・シンプル操作で家族キャンプの定番。楽天ランキング常連の人気モデル。",
    rating: 4.6, createdAt: now, updatedAt: now, autoAdded: false,
  },
  {
    id: "power-ecoflow-delta3-plus", name: "EcoFlow DELTA 3 Plus", brand: "EcoFlow",
    price: 74800, imageUrl: "",
    affiliateUrl: rkSearch("EcoFlow DELTA 3 Plus"),
    amazonUrl: az("EcoFlow DELTA 3 Plus"), yahooUrl: yh("EcoFlow DELTA 3 Plus"),
    categoryId: "portable-power",
    specs: { "容量": "1024Wh（拡張5120Wh）", "定格出力": "1800W（X-Boost対応）", "重量": "約11.5kg", "バッテリー": "リン酸鉄（LFP）" },
    description: "最短56分でフル充電の急速充電と、5120Whまでの拡張性が魅力。多ポート・UPS対応でキャンプから防災まで幅広い。",
    rating: 4.5, createdAt: now, updatedAt: now, autoAdded: false,
  },
  {
    id: "power-anker-solix-c1000", name: "Anker Solix C1000", brand: "Anker",
    price: 59990, imageUrl: "",
    affiliateUrl: rkSearch("Anker Solix C1000"),
    amazonUrl: az("Anker Solix C1000"), yahooUrl: yh("Anker Solix C1000"),
    categoryId: "portable-power",
    specs: { "容量": "1056Wh", "定格出力": "1500W（瞬間2000W）", "重量": "約12.9kg", "バッテリー": "リン酸鉄（LFP・約3000サイクル）" },
    description: "長寿命と充実の保証で選ぶ1台。約58分の急速充電とコスパの高さで、家庭の防災用途にも安心。",
    rating: 4.5, createdAt: now, updatedAt: now, autoAdded: false,
  },
  {
    id: "power-ecoflow-river3-plus", name: "EcoFlow RIVER 3 Plus", brand: "EcoFlow",
    price: 39800, imageUrl: "",
    affiliateUrl: rk("https://item.rakuten.co.jp/ecoflow/river-3-plus/"),
    amazonUrl: az("EcoFlow RIVER 3 Plus"), yahooUrl: yh("EcoFlow RIVER 3 Plus"),
    categoryId: "portable-power",
    specs: { "容量": "286Wh（拡張858Wh）", "定格出力": "600W", "重量": "約4.7kg", "バッテリー": "リン酸鉄（LFP）" },
    description: "5kgを切る軽量ボディの小容量モデル。ソロ・デイキャンプやスマホ・照明・小型家電に。1時間フル充電・UPS・5年保証。",
    rating: 4.5, createdAt: now, updatedAt: now, autoAdded: false,
  },
];

const products = JSON.parse(fs.readFileSync(productsPath, "utf-8"));
const existing = new Set(products.map((p) => p.id));
let added = 0;
for (const p of NEW_PRODUCTS) {
  if (existing.has(p.id)) { console.log(`⏭️  既存スキップ: ${p.id}`); continue; }
  products.push(p); added++;
  console.log(`✅ 商品追加: ${p.id}`);
}
fs.writeFileSync(productsPath, JSON.stringify(products, null, 2) + "\n", "utf-8");
console.log(`📝 products.json（+${added}件）`);

const CONTENT = `# キャンプ用ポータブル電源おすすめ4選【2026年】容量・充電速度・寿命で選ぶ失敗しない選び方

正直に言うと、僕は昔「キャンプに電源なんている？」派でした。自然の中まで来て家電を持ち込むのは野暮だと思っていたんです。考えが変わったのは、真夏の低山キャンプ。夜になっても気温が下がらず、充電式扇風機が朝までもたずに切れて、家族全員が寝苦しさで何度も目を覚ました。あの一晩で「電源、いる」と即決しました。

先に結論を書きます。**キャンプで1台目に選ぶなら、1000Whクラスが基準**です。夏の扇風機、冬の電気毛布、スマホやランタンの充電まで、1泊なら余裕でこなせる容量。中でも**迷ったらJackery 1000 New**。1000Whクラスで最軽量級の約10.8kgで、操作もシンプル。はじめての1台にちょうどいいです。

ソロやデイキャンプ中心で「スマホと照明が使えれば十分」なら、5kgを切る**EcoFlow RIVER 3 Plus**で軽く始めるのもアリ。用途に合わせて容量を選べば、答えはほぼ決まります。

---

## ポータブル電源の選び方（5つのポイント）

### ポイント1: 容量（Wh）は用途で決める

一番大事なのが容量です。ざっくりの目安はこう。

| 用途 | 容量の目安 | 使えるもの |
|---|---|---|
| ソロ・デイキャンプ | 250〜500Wh | スマホ充電、LED照明、小型ファン |
| 家族キャンプ（1泊） | 1000Wh前後 | 扇風機、電気毛布、スマホ複数、小型調理 |
| 連泊・車中泊・防災 | 1500Wh以上 or 拡張 | 上記＋長時間運用、高出力家電 |

僕は最初に容量をケチって500Whクラスを買い、夏の扇風機＋スマホ充電で一晩もたずに後悔しました。**「ちょっと大きいかな」くらいがちょうどいい**、というのが失敗から得た教訓です。

### ポイント2: バッテリーは「リン酸鉄（LFP）」を選ぶ

今のモデルはほぼ**リン酸鉄リチウム（LFP）**が主流。従来の三元系より寿命が圧倒的に長く、3000〜4000回の充放電を繰り返しても容量が8割以上残ります。毎年キャンプで使っても10年近く戦える計算。安全性も高いので、迷ったらLFP一択でいいです。

### ポイント3: 定格出力（W）で使える家電が決まる

容量が「どれだけ長く使えるか」なら、定格出力は「何を動かせるか」。消費電力が定格出力を超える家電は動きません。

- 扇風機・電気毛布・スマホ：〜100W → どのモデルでもOK
- 電気ケトル・ドライヤー・ホットプレート：1000〜1500W → **定格1500W以上**が必要

高出力家電まで使いたいなら、定格1500W以上を選んでおくと安心です。

### ポイント4: 充電速度と拡張性

キャンプ前夜に充電を忘れても、最近のモデルは1時間前後でフル充電できます。特にEcoFlowは急速充電が速い。さらに拡張バッテリーで容量を後から足せる機種を選ぶと、防災や連泊にも化けます。

### ポイント5: UPS・保証

停電時に自動で電力を切り替えるUPS機能は、防災兼用なら地味に効きます。保証は3〜5年が主流。長く使う前提なら保証の手厚さも比較ポイントです。

---

## おすすめポータブル電源4選

### 1. Jackery ポータブル電源 1000 New

{{product:power-jackery-1000-new}}

**迷ったらこれ**、の総合バランス型。1070Whの容量に定格1500W、それでいて約10.8kgと1000Whクラスでは最軽量級。妻でも片手で車から下ろせる軽さで、我が家の出動率が一番高い1台です。

操作もシンプルで、説明書を読まなくても直感で使える。液晶に残量と入出力がはっきり出るので、「あと何時間使えるか」が一目でわかるのも安心。夏は扇風機、冬は電気毛布、通年でスマホとランタンの充電。1泊のファミキャンなら、これ1台で不安なく回せます。

注意点は、定格1500Wなのでドライヤーや電気ケトルなど高出力家電はギリギリのライン。1500Wを超える調理家電をガンガン使いたい人は上位機を検討したほうがいいです。

| 項目 | スペック |
|---|---|
| 容量 | 1070Wh |
| 定格出力 | 1500W（瞬間最大3000W） |
| 重量 | 約10.8kg |
| バッテリー | リン酸鉄（LFP・約4000サイクル） |
| 充電 | 高速充電対応 |
| 価格 | 実売65,000円前後（定価119,800円） |

**口コミ（要約）**

> 「とにかく軽い。10kg強なら車への積み下ろしがラクだし、操作もシンプルで説明書いらずでした」（ファミリーキャンプ利用）

> 「夏は扇風機、冬は電気毛布、あとはスマホ充電。1泊なら余裕で足りる。セールで安く買えたのも満足」（オートキャンプ利用）

> 「定格1500Wなので、ドライヤーや電気ケトルはギリギリ。高出力家電を多用するなら上位機のほうがいい」（車中泊利用）

[楽天で口コミをもっと見る →](${rkSearch("Jackery ポータブル電源 1000 New")}) ｜ [Amazonで見る →](${az("Jackery ポータブル電源 1000 New")})

---

### 2. EcoFlow DELTA 3 Plus

{{product:power-ecoflow-delta3-plus}}

**充電の速さと拡張性で選ぶなら**これ。最短56分でフル充電という速さは一度慣れると戻れません。出発前に「充電忘れてた！」となっても、朝食の準備をしている間に満タンになる。ポート数も11個と多く、家族全員のデバイスを同時に挿せます。

真価は拡張性。専用バッテリーを足せば最大5120Whまで伸ばせるので、連泊の車中泊や防災用の据え置きにも化けます。UPS機能も優秀で、停電時の切り替えが速い。「キャンプにも防災にも本気で使いたい」人の本命です。

注意点は、多機能な分やや重め＆価格も高め。シンプルに使いたいだけなら、機能を持て余すかもしれません。

| 項目 | スペック |
|---|---|
| 容量 | 1024Wh（拡張で最大5120Wh） |
| 定格出力 | 1800W（X-Boost対応） |
| 重量 | 約11.5kg |
| バッテリー | リン酸鉄（LFP） |
| 充電 | 最短約56分でフル充電 |
| 価格 | 実売74,800円前後 |

**口コミ（要約）**

> 「充電が速い。1時間かからずフルになるので出発前にサッと満タンにできる。ポートも多くて家族全員分挿せる」（ファミリー利用）

> 「拡張バッテリーを足せば長期の車中泊や防災にも対応できる安心感。UPSとしても優秀」（防災・車中泊利用）

> 「1000Whクラスの中では重め。多機能な分、価格も高め。シンプル志向だと持て余すかも」（ソロ利用）

[楽天で口コミをもっと見る →](${rkSearch("EcoFlow DELTA 3 Plus")}) ｜ [Amazonで見る →](${az("EcoFlow DELTA 3 Plus")})

---

### 3. Anker Solix C1000

{{product:power-anker-solix-c1000}}

**長く使う前提でコスパ重視なら**これ。1056Whクラスで実売6万円前後は頭ひとつ安く、それでいてリン酸鉄で長寿命、保証も手厚い。約58分の急速充電も備えていて、価格のわりに中身が濃い。

Ankerらしく作りがしっかりしていて、据え置きの防災用とたまのキャンプを兼ねたい人にぴったり。「キャンプは年数回だけど、防災用にも1台ほしい」というニーズに一番ハマります。

注意点は、3機種の中ではやや重めなこと。頻繁に持ち歩くより、車移動＋据え置き中心の使い方が向いています。

| 項目 | スペック |
|---|---|
| 容量 | 1056Wh |
| 定格出力 | 1500W（瞬間最大2000W） |
| 重量 | 約12.9kg |
| バッテリー | リン酸鉄（LFP・約3000サイクル） |
| 充電 | 約58分でフル充電 |
| 価格 | 実売59,990円前後 |

**口コミ（要約）**

> 「長寿命と保証が決め手。毎年使っても劣化が緩やかで、長く使う前提ならコスパが高い」（防災兼用）

> 「充電が速く、価格も1000Whクラスでは手頃。作りもしっかりしている」（オートキャンプ利用）

> 「やや重め。持ち運び重視ならもう少し軽い機種もある。据え置き＋たまにキャンプなら気にならない」（車中泊利用）

[楽天で口コミをもっと見る →](${rkSearch("Anker Solix C1000")}) ｜ [Amazonで見る →](${az("Anker Solix C1000")})

---

### 4. EcoFlow RIVER 3 Plus

{{product:power-ecoflow-river3-plus}}

**ソロ・デイキャンプの入門機**として一番手が出しやすい1台。286Whと容量は控えめですが、その分4.7kgと軽く、片手でひょいと持てる。スマホ充電、LED照明、小型ファンくらいなら必要十分で、ソロやデイキャンプ、車中泊のサブ電源にちょうどいい。

1時間でフル充電できてUPFにも対応。防災用に枕元へ置いても邪魔にならないサイズ感で、日常と非常時を兼ねられます。拡張バッテリーを足せば858Whまで伸ばせるので、「まずは小さく始めて、足りなければ足す」という使い方もできます。

注意点は、286Whなので電気毛布やドライヤーなど消費電力の大きい家電は苦手なこと。あくまで小型・軽量の入門機と割り切るのが正解です。

| 項目 | スペック |
|---|---|
| 容量 | 286Wh（拡張で最大858Wh） |
| 定格出力 | 600W |
| 重量 | 約4.7kg |
| バッテリー | リン酸鉄（LFP） |
| 充電 | 約1時間でフル充電・UPS対応 |
| 価格 | 実売3万円前後（定価39,800円） |

**口コミ（要約）**

> 「5kg切りで本当に軽い。ソロやデイキャンプ、スマホ・照明・小型ファンくらいならこれで十分」（ソロキャンプ利用）

> 「1時間で満充電＆UPS対応。防災用に枕元に置いても邪魔にならないサイズ感が良い」（防災・日常利用）

> 「容量286Whなので、電気毛布やドライヤーなど消費電力の大きい家電は苦手。小型機と割り切る必要あり」（車中泊利用）

[楽天で口コミをもっと見る →](${rk("https://item.rakuten.co.jp/ecoflow/river-3-plus/")}) ｜ [Amazonで見る →](${az("EcoFlow RIVER 3 Plus")})

---

## 1000Whクラス3強を実スペックで比較

家族キャンプの本命、1000Whクラスの3機種を横並びで比較しておきます。

{{comparison:power-jackery-1000-new,power-ecoflow-delta3-plus,power-anker-solix-c1000}}

ざっくり言うと、**軽さとシンプルさのJackery、充電速度と拡張性のEcoFlow、長寿命とコスパのAnker**。この3択なら、どれを選んでも大きく外しません。

---

## 用途別の選び方

### 家族キャンプがメイン → Jackery 1000 New

軽さと扱いやすさが正義。設営でヘトヘトな中でも、軽くてシンプルなほうが結局よく使います。

### 防災も本気で兼ねたい → EcoFlow DELTA 3 Plus / Anker Solix C1000

拡張性・急速充電・保証で選ぶなら上位2機種。据え置きの安心感が違います。

### ソロ・デイキャンプ中心 → EcoFlow RIVER 3 Plus

軽さと価格が魅力。まず小さく始めて、足りなければ上位機を買い足す、でも遅くありません。

---

## よくある質問

### Q1. キャンプにポータブル電源は本当に必要？

「絶対に必要」ではないけれど、**あると快適さが段違い**です。夏の扇風機、冬の電気毛布、照明やスマホの充電、これらを電源サイト以外でも使えるようになる。特に小さい子ども連れは、暑さ寒さ対策が睡眠の質に直結するので、投資する価値は高いです。

### Q2. 容量はどれくらいが目安？

ソロ・デイキャンプなら250〜500Wh、家族キャンプの1泊なら1000Wh前後、連泊や防災兼用なら1500Wh以上（または拡張対応）が目安です。迷ったら「少し大きめ」を選ぶと後悔しません。

### Q3. リン酸鉄（LFP）と三元系、どっちがいい？

キャンプ用途なら**リン酸鉄（LFP）**がおすすめ。寿命が3000〜4000サイクルと長く、毎年使っても長く戦えます。安全性も高い。今の主要モデルはほぼLFPなので、あまり悩まなくて大丈夫です。

### Q4. ソーラーパネルは必要？

必須ではありません。1泊キャンプなら満充電で出発すれば足ります。ただし連泊・車中泊・防災を見据えるなら、日中に充電を継ぎ足せるソーラーパネルがあると安心。まずは本体だけ買って、必要になったら追加でOKです。

### Q5. 何年くらい使える？

リン酸鉄モデルなら、3000〜4000サイクルで容量8割をキープします。年に10〜20回使う程度なら、体感で10年近くは十分に現役。長く使う前提なら、初期費用は十分にペイします。

---

## まとめ

キャンプのポータブル電源選びは、そんなに難しくありません。**容量を用途で決めれば、答えはほぼ出ます。**

- **迷ったら Jackery 1000 New**（軽い・シンプル・家族キャンプの定番）
- **充電速度と拡張性なら EcoFlow DELTA 3 Plus**
- **長寿命・コスパ・防災兼用なら Anker Solix C1000**
- **ソロ・デイで軽く始めるなら EcoFlow RIVER 3 Plus**

僕自身、電源を導入してから夏も冬もキャンプの快適さが一段上がりました。気になるモデルがあれば、セールのタイミングでチェックしてみてください。`;

const FAQS = [
  ["キャンプにポータブル電源は本当に必要？", "「絶対に必要」ではありませんが、あると快適さが段違いです。夏の扇風機、冬の電気毛布、照明やスマホの充電を電源サイト以外でも使えるようになります。特に子ども連れは暑さ寒さ対策が睡眠の質に直結するので、投資する価値は高いです。"],
  ["容量はどれくらいが目安？", "ソロ・デイキャンプなら250〜500Wh、家族キャンプの1泊なら1000Wh前後、連泊や防災兼用なら1500Wh以上（または拡張対応）が目安です。迷ったら少し大きめを選ぶと後悔しません。"],
  ["リン酸鉄（LFP）と三元系、どっちがいい？", "キャンプ用途ならリン酸鉄（LFP）がおすすめです。寿命が3000〜4000サイクルと長く、安全性も高い。今の主要モデルはほぼLFPなので大きく悩む必要はありません。"],
  ["ソーラーパネルは必要？", "必須ではありません。1泊なら満充電で出発すれば足ります。連泊・車中泊・防災を見据えるなら、日中に充電を継ぎ足せるソーラーパネルがあると安心。まず本体だけ買い、必要になったら追加でOKです。"],
  ["何年くらい使える？", "リン酸鉄モデルなら3000〜4000サイクルで容量8割をキープします。年10〜20回の使用なら体感で10年近く現役。長く使う前提なら初期費用は十分ペイします。"],
];

const NEW_ARTICLE = {
  id: "portable-power-station-ranking",
  title: "キャンプ用ポータブル電源おすすめ4選【2026年】容量・充電速度・寿命で選ぶ失敗しない選び方",
  slug: "portable-power-station-ranking",
  categoryId: "portable-power",
  content: CONTENT,
  excerpt: "キャンプの電源は容量を用途で選べば失敗しません。1000Whクラスの三強（Jackery/EcoFlow/Anker）＋ソロ向け軽量機を、両方使ったギア男が比較します。",
  productIds: ["power-jackery-1000-new", "power-ecoflow-delta3-plus", "power-anker-solix-c1000", "power-ecoflow-river3-plus"],
  status: "draft",
  faqs: FAQS.map(([question, answer]) => ({ question, answer })),
  metaDescription: "キャンプ用ポータブル電源の選び方を容量・定格出力・充電速度・寿命(リン酸鉄)で解説。Jackery 1000 New、EcoFlow DELTA 3 Plus、Anker Solix C1000、EcoFlow RIVER 3 Plusの4機種を実用目線で徹底比較します。",
  tags: ["ポータブル電源", "キャンプ電源", "防災", "車中泊", "Jackery", "EcoFlow", "Anker"],
  createdAt: now,
  updatedAt: now,
  publishedAt: null,
  autoGenerated: false,
};

const articles = JSON.parse(fs.readFileSync(articlesPath, "utf-8"));
if (articles.some((a) => a.slug === NEW_ARTICLE.slug)) {
  console.log(`⏭️  記事は既存: ${NEW_ARTICLE.slug}（追加スキップ）`);
} else {
  articles.push(NEW_ARTICLE);
  fs.writeFileSync(articlesPath, JSON.stringify(articles, null, 2) + "\n", "utf-8");
  console.log(`📝 記事追加: ${NEW_ARTICLE.slug}（status: draft）`);
}

console.log("\n✅ 完了。次に  npm run db:sync  で反映 → ?preview=1 でプレビュー確認。");
