#!/usr/bin/env node

/**
 * ポータブル電源記事の画像設定（4商品）
 * 使い方: node scripts/apply-power-images.mjs  →  npm run db:sync
 */

import fs from "fs";
import path from "path";
import { fileURLToPath } from "url";

const ROOT = path.join(path.dirname(fileURLToPath(import.meta.url)), "..");
const productsPath = path.join(ROOT, "data", "products.json");
const now = new Date().toISOString();

const IMAGES = {
  "power-jackery-1000-new": "https://m.media-amazon.com/images/I/51cgrzCirhL._AC_SL1500_.jpg",
  "power-ecoflow-delta3-plus": "https://m.media-amazon.com/images/I/61I0m5mXdcL._AC_SL1500_.jpg",
  "power-anker-solix-c1000": "https://m.media-amazon.com/images/I/51YsPaYII9L._AC_SL1500_.jpg",
  "power-ecoflow-river3-plus": "https://m.media-amazon.com/images/I/61IG+3OJPcL._AC_SL1500_.jpg",
};

const products = JSON.parse(fs.readFileSync(productsPath, "utf-8"));
const byId = Object.fromEntries(products.map((p) => [p.id, p]));

let n = 0;
for (const [id, url] of Object.entries(IMAGES)) {
  if (!byId[id]) { console.log(`⚠️ 商品なし: ${id}`); continue; }
  byId[id].imageUrl = url;
  byId[id].updatedAt = now;
  console.log(`✅ ${id}: ${url}`);
  n++;
}

fs.writeFileSync(productsPath, JSON.stringify(products, null, 2) + "\n", "utf-8");
console.log(`\n📝 products.json 更新（${n}件）。次に  npm run db:sync  で反映。`);
