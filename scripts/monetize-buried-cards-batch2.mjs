#!/usr/bin/env node

/**
 * 埋蔵金・第2弾: productId割当済みなのにカード0の記事に商品カードを挿入。
 *  - picogrill-vs-tokyocamp-bonfire: 対決記事。各「選ぶべき人」節にカード
 *  - spring-camp-clothing-guide: アフィリンク0の純埋蔵金。アウター節にレインウェア3枚
 * 商品は全て affiliateUrl / imageUrl 済み。表示するだけで収益化される。
 * 使い方: node scripts/monetize-buried-cards-batch2.mjs  →  npm run db:sync
 * ※ 冪等
 */

import fs from "fs";
import path from "path";
import { fileURLToPath } from "url";

const ROOT = path.join(path.dirname(fileURLToPath(import.meta.url)), "..");
const articlesPath = path.join(ROOT, "data", "articles.json");
const now = new Date().toISOString();

const articles = JSON.parse(fs.readFileSync(articlesPath, "utf-8"));
let touched = 0;

// --- 1. picogrill-vs-tokyocamp-bonfire: 各「選ぶべき人」見出し直後にカード ---
{
  const a = articles.find((x) => x.slug === "picogrill-vs-tokyocamp-bonfire");
  if (!a) { console.log("⚠️ 記事なし: picogrill-vs-tokyocamp-bonfire"); }
  else {
    const inserts = [
      ["## ピコグリル398を選ぶべき人", "firepit-picogrill-398"],
      ["## Tokyo Camp焚火台を選ぶべき人", "firepit-tokyocamp"],
    ];
    let n = 0;
    for (const [heading, pid] of inserts) {
      const tag = `{{product:${pid}}}`;
      if (a.content.includes(tag)) { console.log(`  ⏭️ 既存: picogrill / ${pid}`); continue; }
      const anchor = `${heading}\n\n`;
      if (!a.content.includes(anchor)) { console.log(`  ⚠️ 見出し無し: ${heading}`); continue; }
      a.content = a.content.replace(anchor, `${anchor}${tag}\n\n`);
      n++;
    }
    if (n) { a.updatedAt = now; touched++; console.log(`✅ picogrill-vs-tokyocamp-bonfire: カード ${n} 枚`); }
  }
}

// --- 2. spring-camp-clothing-guide: アウターレイヤー節にレインウェア3枚 ---
{
  const a = articles.find((x) => x.slug === "spring-camp-clothing-guide");
  if (!a) { console.log("⚠️ 記事なし: spring-camp-clothing-guide"); }
  else {
    const pids = ["rw-001", "rw-002", "rw-003"];
    const anchor = "ゴアテックスが最強ですが、モンベルのドライテックやミズノのベルグテックEXでもGWキャンプには十分対応できます。";
    const lead = "参考までに、僕がGWキャンプで信頼している防水シェルを挙げておきます。ゴアテックスの定番から、コスパのいい国産透湿素材まで、この3枚なら間違いありません。";
    const cards = pids.map((p) => `{{product:${p}}}`).join("\n\n");
    if (pids.every((p) => a.content.includes(`{{product:${p}}}`))) {
      console.log("  ⏭️ 既存: spring-camp-clothing-guide");
    } else if (!a.content.includes(anchor)) {
      console.log("  ⚠️ アンカー無し: spring-camp-clothing-guide");
    } else {
      a.content = a.content.replace(anchor, `${anchor}\n\n${lead}\n\n${cards}`);
      a.updatedAt = now; touched++;
      console.log(`✅ spring-camp-clothing-guide: カード ${pids.length} 枚`);
    }
  }
}

fs.writeFileSync(articlesPath, JSON.stringify(articles, null, 2) + "\n", "utf-8");
console.log(`\n📝 ${touched} 記事を更新。次に  npm run db:sync  で反映してください。`);
