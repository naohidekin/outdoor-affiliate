#!/usr/bin/env node

/**
 * ポータブルクーラー記事の画像修正（EcoFlow WAVE 3 / WAVE 2）
 * 使い方: node scripts/apply-cooler-images.mjs  →  npm run db:sync
 */

import fs from "fs";
import path from "path";
import { fileURLToPath } from "url";

const ROOT = path.join(path.dirname(fileURLToPath(import.meta.url)), "..");
const productsPath = path.join(ROOT, "data", "products.json");
const now = new Date().toISOString();

const IMAGES = {
  "cooler-ecoflow-wave3": "https://m.media-amazon.com/images/I/6158bxPY2QL._AC_SL1500_.jpg",
  "cooler-ecoflow-wave2": "https://m.media-amazon.com/images/I/71+WhUKCkjL._AC_SL1500_.jpg",
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
