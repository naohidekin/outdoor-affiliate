#!/usr/bin/env node

/**
 * コットvsマット記事の画像修正（8商品）
 * 使い方: node scripts/apply-cot-images.mjs  →  npm run db:sync
 */

import fs from "fs";
import path from "path";
import { fileURLToPath } from "url";

const ROOT = path.join(path.dirname(fileURLToPath(import.meta.url)), "..");
const productsPath = path.join(ROOT, "data", "products.json");
const now = new Date().toISOString();

const IMAGES = {
  "cot-helinox-cot-one": "https://m.media-amazon.com/images/I/51ztfTwTuDL._AC_SL1500_.jpg",
  "cot-waq-2way": "https://m.media-amazon.com/images/I/51SD-zbmccL._AC_SL1000_.jpg",
  "cot-dod-baginbed": "https://m.media-amazon.com/images/I/613ie+Rd5uL._AC_SL1500_.jpg",
  "cot-naturehike-greenfield": "https://m.media-amazon.com/images/I/510tCgwRs9L._AC_SL1500_.jpg",
  "mat-coleman-highpeak": "https://m.media-amazon.com/images/I/513QbmXPp2L._AC_SL1500_.jpg",
  "mat-waq-8cm": "https://m.media-amazon.com/images/I/51A4n5tmE+L._AC_SL1000_.jpg",
  "mat-waq-10cm": "https://m.media-amazon.com/images/I/517ROvCdVkL._AC_SL1000_.jpg",
  "mat-thermarest-prolite": "https://m.media-amazon.com/images/I/61tHg59Q1ML._AC_SL1440_.jpg",
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
