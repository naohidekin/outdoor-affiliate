#!/usr/bin/env node

/**
 * 熱中症記事で差し替えた2商品の画像を、不安定な /images/P/ 形式から
 * 実物の /images/I/ URL に修正する。
 * 使い方: node scripts/fix-neck-swap-images.mjs  →  npm run db:sync
 * ※ 冪等
 */

import fs from "fs";
import path from "path";
import { fileURLToPath } from "url";

const ROOT = path.join(path.dirname(fileURLToPath(import.meta.url)), "..");
const productsPath = path.join(ROOT, "data", "products.json");

const IMAGES = {
  "neck-suo-ring": "https://m.media-amazon.com/images/I/31JjnJAMYwL._AC_SL1000_.jpg",
  "neck-mizuno-cooling-towel": "https://m.media-amazon.com/images/I/41xq5YpNSYL._AC_SL1000_.jpg",
};

const products = JSON.parse(fs.readFileSync(productsPath, "utf-8"));
let changed = 0;
for (const [id, url] of Object.entries(IMAGES)) {
  const p = products.find((x) => x.id === id);
  if (!p) { console.log(`⚠️ 商品なし: ${id}`); continue; }
  if (p.imageUrl === url) { console.log(`  ⏭️ 既存: ${id}`); continue; }
  console.log(`✅ ${id}: ${p.imageUrl} → ${url}`);
  p.imageUrl = url;
  changed++;
}
if (changed) {
  fs.writeFileSync(productsPath, JSON.stringify(products, null, 2) + "\n", "utf-8");
  console.log(`\n📦 ${changed} 件更新。次に  npm run db:sync  で反映してください。`);
} else {
  console.log("\n📦 変更なし（適用済み）。");
}
