#!/usr/bin/env node

/**
 * 単一製品レビュー(カード1枚=冒頭のみ)に、まとめ直後の「クロージングカード」を追加。
 * 読者が読み終えて納得した瞬間＝最もコンバージョンしやすい位置に、
 * レビュー対象と同じ製品カードを1枚だけ置く。他製品を混ぜず、正直レビューのトーンを保つ。
 * (他の10年レビュー系が既に採用している 冒頭+末尾 の2枚パターンに揃える)
 * 使い方: node scripts/monetize-review-closing-cards.mjs  →  npm run db:sync
 * ※ 冪等
 */

import fs from "fs";
import path from "path";
import { fileURLToPath } from "url";

const ROOT = path.join(path.dirname(fileURLToPath(import.meta.url)), "..");
const articlesPath = path.join(ROOT, "data", "articles.json");
const now = new Date().toISOString();

// slug -> { pid, anchor(この文の直後に挿入), lead(カード前の一文) }
const PLAN = {
  "dd-hammock-review": {
    pid: "dd-hammock-frontline",
    anchor: "そのステップを1本で賄えるのがこのハンモックの強さです。気になる方はチェックしてみてください。",
    lead: "",
  },
  "stanley-water-jug-review": {
    pid: "stanley-water-jug-7.5l",
    anchor: "夏キャンプの水問題をこれ一台で片付けたい方は、気になったらチェックしてみてください。",
    lead: "",
  },
  "snowpeak-piledriver-review": {
    pid: "lantern-stand-001",
    anchor: "行くキャンプ場のレビューで「地面の状態」を事前確認してから購入を判断してください。",
    lead: "打ち込めるサイトが前提の道具ですが、そこさえ合えば10年裏切らない一本です。",
  },
  "snowpeak-peg-hammer-proc-review": {
    pid: "peg-hammer-snowpeak-proc-review",
    anchor: "「安物を買い替え続けるより安い」と本気で思っている。",
    lead: "長く使うほど元が取れるハンマーです。気になった方はここからどうぞ。",
  },
};

const articles = JSON.parse(fs.readFileSync(articlesPath, "utf-8"));
let done = 0;
for (const [slug, { pid, anchor, lead }] of Object.entries(PLAN)) {
  const a = articles.find((x) => x.slug === slug);
  if (!a) { console.log(`⚠️ 記事なし: ${slug}`); continue; }
  const card = `{{product:${pid}}}`;
  // 同じ製品カードが2枚以上あれば既にクロージング追加済みとみなす（冪等判定）
  const cardCount = (a.content.match(new RegExp(`\\{\\{product:${pid.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")}\\}\\}`, "g")) || []).length;
  if (cardCount >= 2) { console.log(`  ⏭️ 既存(クロージング済): ${slug}`); continue; }
  if (!a.content.includes(anchor)) { console.log(`  ⚠️ アンカー無し: ${slug} / ${anchor.slice(0, 20)}…`); continue; }
  const block = lead ? `${anchor}\n\n${lead}\n\n${card}` : `${anchor}\n\n${card}`;
  a.content = a.content.replace(anchor, block);
  a.updatedAt = now;
  done++;
  console.log(`✅ クロージングカード追加: ${slug} (${pid})`);
}
fs.writeFileSync(articlesPath, JSON.stringify(articles, null, 2) + "\n", "utf-8");
console.log(`\n📝 ${done} 記事にクロージングカードを追加。次に  npm run db:sync  で反映してください。`);
