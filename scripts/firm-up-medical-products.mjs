#!/usr/bin/env node

/**
 * 医師系・CO記事の「ノーブランド／画像なし」商品を確定情報で固める。
 * ユーザー確定の判断に基づく:
 *  - 画像確定3件: ポイズンリムーバー / マダニ除去ツール / 4in1 COチェッカー
 *  - WBGT計 → タニタ TC-210 に確定（名称・ブランド・Amazonリンク・画像を更新）
 *  - DOD CO2チェッカー → Amazon取扱なし。楽天のみ（amazonUrl を空に）
 *  - バーンエイド → 該当品見つからず。ノーブランドのまま画像なしで維持
 *  - 熱中症記事の汎用カード2枚を既存ブランド品へ差し替え + 本文を子ども向けPCM推奨に調整
 * 使い方: node scripts/firm-up-medical-products.mjs  →  npm run db:sync
 * ※ 冪等
 */

import fs from "fs";
import path from "path";
import { fileURLToPath } from "url";

const ROOT = path.join(path.dirname(fileURLToPath(import.meta.url)), "..");
const productsPath = path.join(ROOT, "data", "products.json");
const articlesPath = path.join(ROOT, "data", "articles.json");
const now = new Date().toISOString();
const IMG = (hash) => `https://m.media-amazon.com/images/I/${hash}._AC_SL1500_.jpg`;

// ---- products.json ----
const products = JSON.parse(fs.readFileSync(productsPath, "utf-8"));
const byId = (id) => products.find((p) => p.id === id);
let pChanged = 0;

// 画像確定3件（ノーブランドのまま実物画像を付与）
const imageOnly = {
  "first-aid-poison-remover": "61jW3yOT1ML",
  "first-aid-tick-remover": "6173TXTLvsL",
  "co-detector-4in1": "717BssztyWL",
};
for (const [id, hash] of Object.entries(imageOnly)) {
  const p = byId(id);
  if (!p) { console.log(`⚠️ 商品なし: ${id}`); continue; }
  const url = IMG(hash);
  if (p.imageUrl === url) { console.log(`  ⏭️ 画像済: ${id}`); continue; }
  p.imageUrl = url;
  pChanged++;
  console.log(`✅ 画像設定: ${id}`);
}

// WBGT計 → タニタ TC-210 に確定
const wbgt = byId("heatstroke-wbgt-meter");
if (wbgt) {
  const next = {
    name: "タニタ 黒球式熱中症指数計 TC-210",
    brand: "タニタ",
    imageUrl: IMG("614lRNcFicL"),
    amazonUrl: "https://www.amazon.co.jp/dp/B091PDJFJV/?tag=camp78-22",
  };
  let touched = false;
  for (const [k, v] of Object.entries(next)) {
    if (wbgt[k] !== v) { wbgt[k] = v; touched = true; }
  }
  if (touched) { pChanged++; console.log("✅ WBGT計 → タニタ TC-210 に確定"); }
  else console.log("  ⏭️ WBGT計: 既に確定済");
} else console.log("⚠️ 商品なし: heatstroke-wbgt-meter");

// DOD CO2チェッカー → Amazon取扱なし。楽天のみに
const dod = byId("co-detector-dod-cg1559");
if (dod) {
  if (dod.amazonUrl) { dod.amazonUrl = ""; pChanged++; console.log("✅ DOD COチェッカー → 楽天のみ(Amazon空)"); }
  else console.log("  ⏭️ DOD COチェッカー: 既に楽天のみ");
} else console.log("⚠️ 商品なし: co-detector-dod-cg1559");

if (pChanged) {
  fs.writeFileSync(productsPath, JSON.stringify(products, null, 2) + "\n", "utf-8");
  console.log(`📦 products.json: ${pChanged} 件更新`);
} else console.log("📦 products.json: 変更なし");

// ---- articles.json ----
const articles = JSON.parse(fs.readFileSync(articlesPath, "utf-8"));
const heat = articles.find((a) => a.slug === "kids-camp-heatstroke-prevention");
let aChanged = false;

if (!heat) {
  console.log("⚠️ 記事なし: kids-camp-heatstroke-prevention");
} else {
  let c = heat.content;

  // 汎用カード → 既存ブランド品へ差し替え
  const swaps = [
    ["{{product:heatstroke-neck-cooler-kids}}", "{{product:neck-suo-ring}}"],
    ["{{product:heatstroke-cooling-towel}}", "{{product:neck-mizuno-cooling-towel}}"],
  ];
  for (const [from, to] of swaps) {
    if (c.includes(to)) { console.log(`  ⏭️ 差替済: ${to}`); continue; }
    if (c.includes(from)) { c = c.replace(from, to); aChanged = true; console.log(`✅ 差替: ${from} → ${to}`); }
    else console.log(`  ⚠️ カード無し(ユーザー環境で適用): ${from}`);
  }

  // 子ども向けネッククーラー本文: 電動推奨 → PCMリング推奨へ調整
  const oldPara =
    "電動タイプのネッククーラーは、ペルティエ素子を使って首に直接冷風を当てるか、冷たいプレートを押し当てる仕組みです。充電式で長時間使えるモデルが子連れキャンプに向いています。\n\n子ども向けは首のサイズに合わせてフィットするものを選ぶことが重要です。Sサイズ・子ども用と書かれているモデルを確認してください。首が細い幼児には首掛けUVカット帽子との組み合わせも有効です。";
  const newPara =
    "子ども用のネッククーラーは、電動（ペルティエ素子）タイプよりPCM素材のネックリングを僕はおすすめします。28℃前後で自然に凍る保冷剤が入っていて、冷蔵庫はもちろん、キャンプ場でも水道水や日陰で固まり直します。電源がいらないので、電動タイプのように「充電を忘れて使えない」ということがありません。金属プレートやモーターがない分、子どもの首まわりの肌トラブルや低温やけどの心配も少なくて安心です。\n\nサイズはSやMなど複数展開されているモデルだと、子どもの細い首にもフィットさせやすいです。首が細い幼児には、ネックリングに加えて首掛けUVカット帽子を合わせると効果が上がります。";
  if (c.includes(newPara)) {
    console.log("  ⏭️ 本文調整済: 子ども向けネッククーラー");
  } else if (c.includes(oldPara)) {
    c = c.replace(oldPara, newPara);
    aChanged = true;
    console.log("✅ 本文調整: 子ども向けネッククーラー(PCMリング推奨)");
  } else {
    console.log("  ⚠️ 本文パターン不一致: 子ども向けネッククーラー");
  }

  if (aChanged) {
    heat.content = c;
    heat.updatedAt = now;
    fs.writeFileSync(articlesPath, JSON.stringify(articles, null, 2) + "\n", "utf-8");
    console.log("📝 articles.json: kids-camp-heatstroke-prevention 更新");
  } else console.log("📝 articles.json: 変更なし");
}

console.log("\n次に  npm run db:sync  で反映してください。");
