#!/usr/bin/env node

/**
 * 秋クラスターの残り2本（ハブ／服装）を公開する。
 * create-autumn-camp-complete-guide.mjs / create-autumn-clothing-guide.mjs で
 * 作成した下書きを status=published に。
 * 使い方: node scripts/publish-autumn-cluster.mjs  →  npm run db:sync
 * ※ 冪等
 */

import fs from "fs";
import path from "path";
import { fileURLToPath } from "url";

const ROOT = path.join(path.dirname(fileURLToPath(import.meta.url)), "..");
const articlesPath = path.join(ROOT, "data", "articles.json");
const now = new Date().toISOString();
const SLUGS = ["autumn-camp-complete-guide", "autumn-camp-clothing-layering-guide"];

const articles = JSON.parse(fs.readFileSync(articlesPath, "utf-8"));
let changed = 0;
for (const slug of SLUGS) {
  const a = articles.find((x) => x.slug === slug);
  if (!a) { console.log(`⚠️ 記事なし: ${slug}（先に create-系スクリプトを実行）`); continue; }
  if (a.status === "published") { console.log(`  ⏭️ 既に公開済み: ${slug}`); continue; }
  a.status = "published";
  if (!a.publishedAt) a.publishedAt = now;
  a.updatedAt = now;
  changed++;
  console.log(`✅ 公開: ${slug}`);
}
if (changed) fs.writeFileSync(articlesPath, JSON.stringify(articles, null, 2) + "\n", "utf-8");
console.log(`\n📝 ${changed} 本を公開。次に  npm run db:sync  で反映してください。`);
