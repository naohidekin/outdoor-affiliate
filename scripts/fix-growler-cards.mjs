#!/usr/bin/env node

/**
 * growler-comparison-summer-ice の画像不具合を修正（A: カード化）
 *  - 詳細評価3商品を {{product:growler-001/002/003}} カードに（既存の正常画像を使用）
 *  - 「7年使った」節の壊れURL(_SL500_)を _SL1500_ に修正
 *  - カードと重複するインラインAmazon/楽天リンクを除去
 * 使い方: node scripts/fix-growler-cards.mjs  →  npm run db:sync
 */

import fs from "fs";
import path from "path";
import { fileURLToPath } from "url";

const ROOT = path.join(path.dirname(fileURLToPath(import.meta.url)), "..");
const articlesPath = path.join(ROOT, "data", "articles.json");
const now = new Date().toISOString();

const articles = JSON.parse(fs.readFileSync(articlesPath, "utf-8"));
const art = articles.find((a) => a.slug === "growler-comparison-summer-ice");
if (!art) { console.error("❌ 記事なし"); process.exit(1); }

let c = art.content;
const reps = [
  // 「7年使った」節: 壊れURLを正常なSL1500へ
  ["![スタンレー クラシック真空グロウラー 1.9L](https://m.media-amazon.com/images/I/51AHvcGKkcL._AC_SL500_.jpg)",
   "![スタンレー クラシック真空グロウラー 1.9L](https://m.media-amazon.com/images/I/51AHvcGKkcL._AC_SL1500_.jpg)"],
  // 詳細評価3商品をカード化
  ["![スタンレー クラシック真空グロウラー](https://m.media-amazon.com/images/I/61Tcx9PuT0L._AC_SL500_.jpg)",
   "{{product:growler-001}}"],
  ["![ドリンクタンクス グロウラー 64oz](https://m.media-amazon.com/images/I/517plCZhWlL._AC_SL500_.jpg)",
   "{{product:growler-002}}"],
  ["![スタンレー アイスフロー 真空ジャグ](https://m.media-amazon.com/images/I/61oSrWFnmiL._AC_SL500_.jpg)",
   "{{product:growler-003}}"],
];
let applied = 0;
for (const [from, to] of reps) {
  if (c.includes(from)) { c = c.replace(from, to); applied++; }
  else console.log(`⏭️ 対象なし: ${from.slice(0, 30)}…`);
}

// カードと重複するインラインリンクを除去（このリンクはこの記事では商品節のみ）
const beforeLinks = c;
c = c.replace(/\[Amazonで見る →\]\([^)]*\)\n*/g, "");
c = c.replace(/\[楽天で口コミを見る →\]\([^)]*\)\n*/g, "");
const linksRemoved = (beforeLinks.match(/\[(Amazonで見る|楽天で口コミを見る) →\]/g) || []).length;

// 余分な空行を整理
c = c.replace(/\n{3,}/g, "\n\n");

art.content = c;
art.updatedAt = now;
fs.writeFileSync(articlesPath, JSON.stringify(articles, null, 2) + "\n", "utf-8");
console.log(`✅ 画像置換 ${applied}件 / インラインリンク除去 ${linksRemoved}件`);
console.log("次に  npm run db:sync  で反映してください。");
