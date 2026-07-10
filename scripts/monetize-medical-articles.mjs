#!/usr/bin/env node

/**
 * 医師系の良記事(救急セット/熱中症予防)を収益化。
 * 各商品の専用見出し直後に {{product:}} カード(楽天/Amazonボタン付き)を挿入。
 * 商品はproductIds割当済み・affiliateUrlありなので、表示するだけで収益化される。
 * 使い方: node scripts/monetize-medical-articles.mjs  →  npm run db:sync
 * ※ 冪等: 既にカードがあればスキップ
 */

import fs from "fs";
import path from "path";
import { fileURLToPath } from "url";

const ROOT = path.join(path.dirname(fileURLToPath(import.meta.url)), "..");
const articlesPath = path.join(ROOT, "data", "articles.json");
const now = new Date().toISOString();

// slug -> [[見出し, productId], ...]（見出し直後にカードを挿入）
const PLAN = {
  "kids-camp-first-aid-kit": [
    ["### ポイズンリムーバー（毒吸引器）", "first-aid-poison-remover"],
    ["### マダニ除去ツール", "first-aid-tick-remover"],
    ["### やけど用湿潤ドレッシング材（バーンエイド等）", "first-aid-burn-aid"],
  ],
  "kids-camp-heatstroke-prevention": [
    ["### キャンプ向けネッククーラー（子ども用）", "heatstroke-neck-cooler-kids"],
    ["### 冷感タオル（クールタオル）", "heatstroke-cooling-towel"],
    ["### WBGT計（暑さ指数計）", "heatstroke-wbgt-meter"],
  ],
};

const articles = JSON.parse(fs.readFileSync(articlesPath, "utf-8"));
let total = 0;
for (const [slug, inserts] of Object.entries(PLAN)) {
  const a = articles.find((x) => x.slug === slug);
  if (!a) { console.log(`⚠️ 記事なし: ${slug}`); continue; }
  let n = 0;
  for (const [heading, pid] of inserts) {
    const tag = `{{product:${pid}}}`;
    if (a.content.includes(tag)) { console.log(`  ⏭️ 既存: ${slug} / ${pid}`); continue; }
    const anchor = `${heading}\n\n`;
    if (!a.content.includes(anchor)) { console.log(`  ⚠️ 見出し無し: ${slug} / ${heading}`); continue; }
    a.content = a.content.replace(anchor, `${heading}\n\n${tag}\n\n`);
    n++;
  }
  if (n) { a.updatedAt = now; total += n; console.log(`✅ ${slug}: カード ${n} 枚挿入`); }
}
fs.writeFileSync(articlesPath, JSON.stringify(articles, null, 2) + "\n", "utf-8");
console.log(`\n📝 合計 ${total} 枚。次に  npm run db:sync  で反映してください。`);
