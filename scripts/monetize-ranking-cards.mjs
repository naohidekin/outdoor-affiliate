#!/usr/bin/env node

/**
 * Bの仕上げ: インラインリンクのみだったランキング記事を商品カード化。
 *  - 各「### N位：…」見出し直後に {{product:productIds[N-1]}} を挿入
 *  - 重複する末尾CTA行「気になる方はチェックを → [Amazon/楽天]…」を除去(ボタン二重表示を回避)
 * カードは画像+スペック+ボタン+口コミCTAを持つのでCVRが上がる。
 * 対象: water-jug-ranking / family-tent-ranking (どちらも5位・pidは順位順)
 * 使い方: node scripts/monetize-ranking-cards.mjs  →  npm run db:sync
 * ※ 冪等
 */

import fs from "fs";
import path from "path";
import { fileURLToPath } from "url";

const ROOT = path.join(path.dirname(fileURLToPath(import.meta.url)), "..");
const articlesPath = path.join(ROOT, "data", "articles.json");
const now = new Date().toISOString();

const SLUGS = ["water-jug-ranking", "family-tent-ranking"];

const articles = JSON.parse(fs.readFileSync(articlesPath, "utf-8"));
let touched = 0;

for (const slug of SLUGS) {
  const a = articles.find((x) => x.slug === slug);
  if (!a) { console.log(`⚠️ 記事なし: ${slug}`); continue; }
  const pids = a.productIds || [];
  if (pids.length === 0) { console.log(`⚠️ pidなし: ${slug}`); continue; }
  if (a.content.includes(`{{product:${pids[0]}}}`)) { console.log(`  ⏭️ 既存(適用済): ${slug}`); continue; }

  // 1. 各「### N位：」見出し直後にカードを挿入（見出しの出現順＝順位順にpidを割当）
  let idx = 0;
  a.content = a.content.replace(/^(### \d+位[^\n]*)\n\n/gm, (m, heading) => {
    if (idx >= pids.length) return m; // pid数を超える見出しは触らない
    const pid = pids[idx++];
    return `${heading}\n\n{{product:${pid}}}\n\n`;
  });
  const inserted = idx;

  // 2. 重複する末尾CTA行を除去
  const before = a.content;
  a.content = a.content.replace(/\n*^気になる方はチェックを → [^\n]*\n/gm, "\n");
  const removed = (before.match(/^気になる方はチェックを → /gm) || []).length;

  // 3. 余分な空行を整理
  a.content = a.content.replace(/\n{3,}/g, "\n\n");

  a.updatedAt = now;
  touched++;
  console.log(`✅ ${slug}: カード ${inserted} 枚挿入 / 重複CTA ${removed} 行除去`);
}

fs.writeFileSync(articlesPath, JSON.stringify(articles, null, 2) + "\n", "utf-8");
console.log(`\n📝 ${touched} 記事を更新。次に  npm run db:sync  で反映してください。`);
