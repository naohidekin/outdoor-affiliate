#!/usr/bin/env node

/**
 * 埋蔵金記事(良記事なのに商品カード未表示)を一括収益化。
 * 商品はproductIds割当済み・affiliateUrlあり。見出し直後に{{product:}}カードを挿入。
 * GW予算記事のみ商品が文中に散るため末尾に「紹介したギア」節を追加。
 * 使い方: node scripts/monetize-buried-articles.mjs  →  npm run db:sync
 * ※ 冪等
 */

import fs from "fs";
import path from "path";
import { fileURLToPath } from "url";

const ROOT = path.join(path.dirname(fileURLToPath(import.meta.url)), "..");
const articlesPath = path.join(ROOT, "data", "articles.json");
const now = new Date().toISOString();

// slug -> [[見出し, [productId,...]], ...]  見出し直後にカード挿入
const HEADING_INSERTS = {
  "co-detector-camping-guide": [
    ["### 1. 新コスモス電機 COALAN CL-715", ["co-detector-coalan-cl715"]],
    ["### 2. DOD キャンプ用一酸化炭素チェッカー2（CG1-559）", ["co-detector-dod-cg1559"]],
    ["### 3. CO+CO₂+温度+湿度 4in1チェッカー", ["co-detector-4in1"]],
  ],
  "firepit-beginner-guide": [
    ["### ピコグリル398——ソロキャンパーの定番", ["fp-001"]],
    ["### ユニフレーム ファイアグリル——ファミリーキャンプの鉄板", ["fp-002"]],
    ["### スノーピーク 焚火台 L——一生モノの焚き火台", ["fp-003"]],
    ["### Tokyo Camp 焚き火台——5,000円以下のベストバイ", ["fp-004"]],
    ["### ソロストーブ レンジャー2——二次燃焼で煙が少ない", ["fp-005"]],
  ],
  "zane-arts-discontinued-alternatives-2026": [
    ["### サーカスTC DX — ゼクーに一番近い空気感", ["tent-circus-tc-dx"]],
    ["### WAQ Alpha TC/FT — コスパで選ぶならこれ一択", ["tent-waq-alpha-tc"]],
    ["### ogawa ツインピルツフォーク T/C — ギギユーザーの本命", ["tent-ogawa-twin-piltz"]],
  ],
  "amenity-dome-vs-landnest-dome": [
    ["## アメニティドームを選ぶべき人", ["tent-sp-amenity-dome-m"]],
    ["## ランドネストドームを選ぶべき人", ["tent-sp-landnest-dome-m"]],
  ],
  "spring-sleeping-bag-guide": [
    ["### 予算5,000〜10,000円（化繊）", ["sb-budget-001", "sb-budget-002", "sb-budget-003"]],
    ["### 予算25,000〜40,000円（ダウン）", ["sb-nanga-001", "sb-nanga-002"]],
  ],
  "gw-camp-guide-2026": [
    ["## テント選び——GWは「広さ」と「前室」を優先", ["tent-f01", "tent-f03"]],
  ],
};

// slug -> [anchor(前に節を挿入), 見出し, [productId,...]]  末尾節として挿入
const SECTION_INSERTS = {
  "gw-camping-gear-budget": ["## まとめ", "## この記事で紹介したギア",
    ["tent-f01", "tent-f03", "sb-budget-001", "sb-nanga-001", "fp-002", "fp-004"]],
};

const articles = JSON.parse(fs.readFileSync(articlesPath, "utf-8"));
let total = 0;

for (const [slug, inserts] of Object.entries(HEADING_INSERTS)) {
  const a = articles.find((x) => x.slug === slug);
  if (!a) { console.log(`⚠️ 記事なし: ${slug}`); continue; }
  let n = 0;
  for (const [heading, pids] of inserts) {
    const cards = pids.map((p) => `{{product:${p}}}`).join("\n\n");
    if (pids.every((p) => a.content.includes(`{{product:${p}}}`))) { console.log(`  ⏭️ 既存: ${slug} / ${heading.slice(0, 20)}`); continue; }
    const anchor = `${heading}\n\n`;
    if (!a.content.includes(anchor)) { console.log(`  ⚠️ 見出し無し: ${slug} / ${heading}`); continue; }
    a.content = a.content.replace(anchor, `${heading}\n\n${cards}\n\n`);
    n += pids.length;
  }
  if (n) { a.updatedAt = now; total += n; console.log(`✅ ${slug}: カード ${n} 枚`); }
}

for (const [slug, [anchor, secHeading, pids]] of Object.entries(SECTION_INSERTS)) {
  const a = articles.find((x) => x.slug === slug);
  if (!a) { console.log(`⚠️ 記事なし: ${slug}`); continue; }
  if (a.content.includes(secHeading)) { console.log(`  ⏭️ 既存節: ${slug}`); continue; }
  const cards = pids.map((p) => `{{product:${p}}}`).join("\n\n");
  const block = `${secHeading}\n\nこの記事で触れたギアをまとめておきます。気になるものはチェックしてみてください。\n\n${cards}\n\n${anchor}`;
  if (!a.content.includes(anchor)) { console.log(`  ⚠️ アンカー無し: ${slug}`); continue; }
  a.content = a.content.replace(anchor, block);
  a.updatedAt = now; total += pids.length;
  console.log(`✅ ${slug}: 末尾節 + カード ${pids.length} 枚`);
}

fs.writeFileSync(articlesPath, JSON.stringify(articles, null, 2) + "\n", "utf-8");
console.log(`\n📝 合計 ${total} 枚。次に  npm run db:sync  で反映してください。`);
