#!/usr/bin/env node

/**
 * portable-power-station-guide 本文の「重複＆一部リンク切れ」直貼りmarkdown画像を削除。
 * 商品カード({{product:}})が画像を表示するため、本文の ![...](..._AC_SL500_.jpg) は不要。
 * 使い方: node scripts/fix-power-inline-images.mjs  →  npm run db:sync
 */

import fs from "fs";
import path from "path";
import { fileURLToPath } from "url";

const ROOT = path.join(path.dirname(fileURLToPath(import.meta.url)), "..");
const articlesPath = path.join(ROOT, "data", "articles.json");
const now = new Date().toISOString();

const articles = JSON.parse(fs.readFileSync(articlesPath, "utf-8"));
const art = articles.find((a) => a.slug === "portable-power-station-guide");
if (!art) { console.error("❌ 記事なし"); process.exit(1); }

const before = art.content;
// 本文中の Amazon 直貼り画像（![...](m.media-amazon...)）を、前後の空行ごと除去
art.content = art.content.replace(/\n*!\[[^\]]*\]\(https:\/\/m\.media-amazon\.com[^)]*\)\n*/g, "\n\n");

const removed = (before.match(/!\[[^\]]*\]\(https:\/\/m\.media-amazon\.com[^)]*\)/g) || []).length;
if (removed > 0) {
  art.updatedAt = now;
  fs.writeFileSync(articlesPath, JSON.stringify(articles, null, 2) + "\n", "utf-8");
  console.log(`✅ 直貼り画像 ${removed} 枚を削除（カード画像は維持）`);
} else {
  console.log("⏭️ 削除対象の直貼り画像なし（適用済み）");
}
console.log("次に  npm run db:sync  で反映してください。");
