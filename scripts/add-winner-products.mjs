#!/usr/bin/env node

/**
 * アフィリ実績で売れ筋と判明した2商品を追加し、秋の寒さ対策ガイドに差し込む。
 *  - S'more OKURUMI BAG（春秋シュラフ・楽天で¥11,792売れた）
 *  - NEMO Fillo（キャンプ枕・楽天で¥6,580売れた。サイトに枕コンテンツ皆無の盲点）
 * データ駆動の横展開。products.json に追加＋autumn-winter-camp-cold-gear-guideの
 * 「寝る道具」まとめにカード挿入＋productIds更新。
 * 使い方: node scripts/add-winner-products.mjs  →  npm run db:sync
 * ※ 冪等
 */

import fs from "fs";
import path from "path";
import { fileURLToPath } from "url";

const ROOT = path.join(path.dirname(fileURLToPath(import.meta.url)), "..");
const productsPath = path.join(ROOT, "data", "products.json");
const articlesPath = path.join(ROOT, "data", "articles.json");
const now = new Date().toISOString();

const AFF_ID = "18eb3228.621d8df3.18eb3229.ec5f8d49";
const rakuAff = (itemUrl) =>
  `https://hb.afl.rakuten.co.jp/ichiba/${AFF_ID}/?pc=${encodeURIComponent(itemUrl)}&link_type=text&ut=`;

const NEW_PRODUCTS = [
  {
    id: "sb-smore-okurumi",
    name: "S'more スモア OKURUMI BAG 封筒型シュラフ（快適温度5〜15℃）",
    brand: "S'more",
    price: 8800,
    imageUrl: "https://image.rakuten.co.jp/aimoha/cabinet/aimoha6/smore/smoftsj001a300_01.jpg",
    affiliateUrl: rakuAff("https://item.rakuten.co.jp/aimoha/smoftsj001a300/"),
    amazonUrl: "https://www.amazon.co.jp/dp/B09VP8H8XD/?tag=camp78-22",
    categoryId: "sleeping-bag",
    specs: { "快適温度": "5〜15℃", "中綿": "ダウン90%/フェザー10%", "重量": "約580g", "形状": "封筒型（連結可能）", "洗濯": "丸洗いOK" },
    description: "ダウン90%・約580gと軽量コンパクトで、快適温度5〜15℃と春秋にちょうどいい封筒型シュラフ。丸洗いでき、2つ連結すれば掛け布団にもなる。コスパの高い一枚。",
    rating: 4.4,
    createdAt: now, updatedAt: now, priceUpdatedAt: now,
  },
  {
    id: "pillow-nemo-fillo",
    name: "NEMO ニーモ フィッロ Fillo キャンプ枕",
    brand: "NEMO",
    price: 6050,
    imageUrl: "https://image.rakuten.co.jp/canpanera/cabinet/item242/item_n22188_0.jpg",
    affiliateUrl: rakuAff("https://item.rakuten.co.jp/canpanera/n22188/"),
    amazonUrl: "",
    categoryId: "sleeping-bag",
    specs: { "収納サイズ": "約φ10×15cm", "使用サイズ": "約43×27×厚10cm", "重量": "約260g", "カバー": "取り外して洗濯可" },
    description: "3Dバッフル構造とフォーム内蔵で、空気枕とは思えない自然な寝心地。カバーは取り外して洗える。収納約260gで携帯性も高い、キャンプ枕の定番。",
    rating: 4.5,
    createdAt: now, updatedAt: now, priceUpdatedAt: now,
  },
];

// ---- products.json ----
const products = JSON.parse(fs.readFileSync(productsPath, "utf-8"));
let pAdded = 0;
for (const np of NEW_PRODUCTS) {
  if (products.some((p) => p.id === np.id)) { console.log(`  ⏭️ 商品既存: ${np.id}`); continue; }
  products.push(np);
  pAdded++;
  console.log(`✅ 商品追加: ${np.id}（${np.name.slice(0, 20)}…）`);
}
if (pAdded) fs.writeFileSync(productsPath, JSON.stringify(products, null, 2) + "\n", "utf-8");

// ---- 記事に差し込み（autumn-winter-camp-cold-gear-guide）----
const articles = JSON.parse(fs.readFileSync(articlesPath, "utf-8"));
const a = articles.find((x) => x.slug === "autumn-winter-camp-cold-gear-guide");
if (!a) {
  console.log("⚠️ 記事なし: autumn-winter-camp-cold-gear-guide（ユーザー環境で適用されます）");
} else if (a.content.includes("{{product:sb-smore-okurumi}}")) {
  console.log("  ⏭️ 記事挿入済み");
} else {
  const anchor = "{{product:sb-budget-003}}";
  if (a.content.includes(anchor)) {
    const block =
      anchor +
      "\n\n軽さとコスパを両取りしたいなら、ダウン90%で約580g・快適温度5〜15℃のS'more OKURUMI BAGも春秋にちょうどいい一枚です。丸洗いできて連結もできるので、家族での使い回しもしやすいです。" +
      "\n\n{{product:sb-smore-okurumi}}" +
      "\n\n寝袋とマットが決まったら、仕上げは枕です。地味ですが、首元が安定すると朝の首や肩の疲れが驚くほど変わります。かさばらないので1つ持っておくと快適さが段違いです。" +
      "\n\n{{product:pillow-nemo-fillo}}";
    a.content = a.content.replace(anchor, block);
    a.productIds = Array.from(new Set([...(a.productIds || []), "sb-smore-okurumi", "pillow-nemo-fillo"]));
    a.updatedAt = now;
    console.log("✅ 記事に挿入: S'moreシュラフ＋NEMO枕カード / productIds更新");
  } else {
    console.log("  ⚠️ アンカー無し（記事構成が想定と異なる）");
  }
}
fs.writeFileSync(articlesPath, JSON.stringify(articles, null, 2) + "\n", "utf-8");

console.log(`\n📦 商品 ${pAdded} 件追加。次に  npm run db:sync  で反映してください。`);
