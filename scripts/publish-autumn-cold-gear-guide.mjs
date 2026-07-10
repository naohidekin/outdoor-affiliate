#!/usr/bin/env node

/**
 * 秋の新記事「秋冬キャンプの寒さ対策ギア完全ガイド」を公開する。
 * create-autumn-cold-gear-guide.mjs で作成した下書きを status=published に。
 * 使い方: node scripts/publish-autumn-cold-gear-guide.mjs  →  npm run db:sync
 * ※ 冪等
 */

import fs from "fs";
import path from "path";
import { fileURLToPath } from "url";

const ROOT = path.join(path.dirname(fileURLToPath(import.meta.url)), "..");
const articlesPath = path.join(ROOT, "data", "articles.json");
const now = new Date().toISOString();
const SLUG = "autumn-winter-camp-cold-gear-guide";

const articles = JSON.parse(fs.readFileSync(articlesPath, "utf-8"));
const a = articles.find((x) => x.slug === SLUG);
if (!a) {
  console.error(`❌ 記事なし: ${SLUG}（先に create-autumn-cold-gear-guide.mjs を実行してください）`);
  process.exit(1);
}

if (a.status === "published") {
  console.log(`⏭️ 既に公開済み: ${SLUG}`);
} else {
  a.status = "published";
  if (!a.publishedAt) a.publishedAt = now;
  a.updatedAt = now;
  fs.writeFileSync(articlesPath, JSON.stringify(articles, null, 2) + "\n", "utf-8");
  console.log(`✅ 公開: ${SLUG}`);
  console.log(`   status=${a.status} / publishedAt=${a.publishedAt}`);
  console.log(`   カード${(a.content.match(/\{\{product:/g) || []).length}枚 / ${a.content.length}字`);
}
console.log("次に  npm run db:sync  で公開反映してください。");
