#!/usr/bin/env node

/**
 * ネッククーラー記事の仕上げ（一括・gitなしでローカル反映）
 *  1) 5商品に実画像URL（PA-API不要・手取得の /images/I/ ）を設定
 *  2) Sony を REON POCKET 5 → 6 に更新（商品データ＋記事本文＋リンク）
 *
 * 使い方: node scripts/apply-neck-images.mjs
 * 反映:   npm run db:sync   （Supabaseへ）
 */

import fs from "fs";
import path from "path";
import { fileURLToPath } from "url";

const ROOT = path.join(path.dirname(fileURLToPath(import.meta.url)), "..");
const productsPath = path.join(ROOT, "data", "products.json");
const articlesPath = path.join(ROOT, "data", "articles.json");
const now = new Date().toISOString();

// --- 1) 画像URL（手取得の本物 /images/I/ ） ---
const IMAGES = {
  "neck-thanko-lite": "https://m.media-amazon.com/images/I/61+dc2X3k3L._AC_SX679_.jpg",
  "neck-sony-reonpocket5": "https://m.media-amazon.com/images/I/41BEw8t6u4L._AC_SL1000_.jpg",
  "neck-suo-ring": "https://m.media-amazon.com/images/I/410d4U5GL0L._AC_SL1500_.jpg",
  "neck-suo-ring-plus": "https://m.media-amazon.com/images/I/61AzDV5-98L._AC_SL1000_.jpg",
  "neck-mizuno-cooling-towel": "https://m.media-amazon.com/images/I/51xogjdZNoL._AC_SX679_.jpg",
};

const products = JSON.parse(fs.readFileSync(productsPath, "utf-8"));
const byId = Object.fromEntries(products.map((p) => [p.id, p]));

let imgSet = 0;
for (const [id, url] of Object.entries(IMAGES)) {
  if (!byId[id]) { console.log(`⚠️ 商品なし: ${id}`); continue; }
  byId[id].imageUrl = url;
  byId[id].updatedAt = now;
  imgSet++;
}

// --- 2) Sony を POCKET 6 に更新 ---
const sony = byId["neck-sony-reonpocket5"];
if (sony) {
  sony.name = "Sony REON POCKET 6";
  sony.price = 25300;
  sony.amazonUrl = "https://www.amazon.co.jp/dp/B0GTLBDP65?tag=camp78-22";
  sony.affiliateUrl = "https://hb.afl.rakuten.co.jp/ichiba/18eb3228.621d8df3.18eb3229.ec5f8d49/?pc=https%3A%2F%2Fsearch.rakuten.co.jp%2Fsearch%2Fmall%2FSony%2520REON%2520POCKET%25206%2F&link_type=text&ut=";
  sony.yahooUrl = "https://shopping.yahoo.co.jp/search?p=Sony%20REON%20POCKET%206";
  sony.specs = { "重量": "125g", "冷却方式": "電動ペルチェ式（DUAL）", "持続時間": "3〜10時間", "冷温両対応": "対応" };
  sony.updatedAt = now;
  console.log("✅ Sony を REON POCKET 6 に更新");
}

fs.writeFileSync(productsPath, JSON.stringify(products, null, 2) + "\n", "utf-8");
console.log(`📝 products.json 更新（画像 ${imgSet} 件）`);

// --- 3) 記事本文の Sony セクションを POCKET 6 に差し替え ---
const NEW_SONY = `### 2. Sony REON POCKET 6（電動ペルチェ式）

{{product:neck-sony-reonpocket5}}

ネッククーラーの最高峰。実売25,300円と飛び抜けて高いけど、冷却性能・静音性・アプリ連携すべてにおいてクオリティが段違い。2026年5月に出た最新モデルで、上位機ゆずりのDUALサーモモジュールを約125gの小型ボディに詰め込んできた。

前モデルのREON POCKET 5から、冷温部の温度をさらに最大2℃低減。小型モジュールを2枚使うことで、大型化させずに冷却を強化してきたのが今回の目玉。動作音は静かなままで、テント内で使っても家族の睡眠を邪魔しない。約125gの軽さも健在で、首に装着していることを忘れるほど。

COOLモードは5段階。レベル1なら約10時間、レベル3で約7時間、レベル5でも約3時間稼働する。キャンプの夕方〜就寝までを1回の充電でカバーできる計算。強力冷却の分、旧型より駆動時間は控えめなので、モバイルバッテリーでのUSB給電を併用すると安心。充電も速く、約60分で80%、約120分で満充電まで戻せる。

専用アプリでスマホから温度をコントロールできるのも、テント内で寝転がりながら操作できて便利。周囲の温湿度を測る「REON POCKET TAG 2」が同梱されたRNPK-6T（27,500円）を選べば、環境に応じて自動で冷却レベルを調整してくれる。

**ぼくが唯一気になるのは、装着方式。** 首の後ろに本体を当てて、専用のネックバンドまたはインナーウェアのポケットで固定する。ネッククーラーLiteのように首にかけるだけ、とはいかない。動き回る設営中には使いにくくて、チェアに座ってからの使用がメインになる。

| 項目 | スペック |
|---|---|
| メーカー | Sony |
| 型番 | RNPK-6 |
| 冷却方式 | ペルチェ式DUALサーモモジュール |
| 冷却モード | COOLレベル1〜5 |
| 稼働時間 | Lv1: 約10h / Lv3: 約7h / Lv5: 約3h |
| 充電 | USB-C（約60分で80%・約120分で満充電） |
| 重量 | 約125g |
| サイズ | 約53×24×119mm（本体） |
| 発売 | 2026年5月12日 |
| 価格 | 25,300円（税込・ネックバンド付RNPK-6）/ TAG2同梱 RNPK-6T 27,500円 |

**口コミ（要約）**

> 「前モデルより冷えが強くなったのを体感できる。デスクワークや軽い外出なら首元がしっかり涼しい」（在宅ワーク・通勤利用）

> 「充電が速いのが地味に便利。80%まで1時間かからないので、朝の準備中にサッと足せる」（通勤・日常利用）

> 「冷却が強い分、旧モデルよりバッテリーの持ちは短め。長時間ならモバイルバッテリー併用が前提。価格も高い」（屋外・長時間利用）

[楽天で口コミをもっと見る →](https://hb.afl.rakuten.co.jp/ichiba/18eb3228.621d8df3.18eb3229.ec5f8d49/?pc=https%3A%2F%2Fsearch.rakuten.co.jp%2Fsearch%2Fmall%2FSony%2520REON%2520POCKET%25206%2F&link_type=text&ut=) ｜ [Amazonで見る →](https://www.amazon.co.jp/dp/B0GTLBDP65?tag=camp78-22)


`;

const articles = JSON.parse(fs.readFileSync(articlesPath, "utf-8"));
const art = articles.find((a) => a.slug === "neck-cooler-ranking");
if (!art) { console.error("❌ 記事 neck-cooler-ranking が見つかりません"); process.exit(1); }

const startAnchor = "### 2. Sony REON POCKET 5";
const endAnchor = "### 3. SUO";
const si = art.content.indexOf(startAnchor);
const ei = art.content.indexOf(endAnchor);
if (si === -1 || ei === -1) {
  console.error(`❌ Sonyセクションのアンカーが見つかりません (start:${si} end:${ei})。本文が既に変更済みの可能性。`);
  process.exit(1);
}
art.content = art.content.slice(0, si) + NEW_SONY + "---\n\n" + art.content.slice(ei);
art.updatedAt = now;
fs.writeFileSync(articlesPath, JSON.stringify(articles, null, 2) + "\n", "utf-8");
console.log("📝 articles.json の Sonyセクションを POCKET 6 に更新");

console.log("\n✅ 完了。次に  npm run db:sync  でSupabaseへ反映してください。");
