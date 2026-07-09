#!/usr/bin/env node

/**
 * 夏の高集客記事 → 高単価記事 への内部リンクを自然な文脈で追加。
 * データ(Amazon実績)で稼ぎ頭と判明した扇風機・暑さ対策記事から、
 * ポータブルクーラー/ネッククーラー/ポータブル電源へ送客する導線を敷く。
 * 使い方: node scripts/add-internal-links-summer.mjs  →  npm run db:sync
 * ※ 冪等: 既にリンク追加済みならスキップ
 */

import fs from "fs";
import path from "path";
import { fileURLToPath } from "url";

const ROOT = path.join(path.dirname(fileURLToPath(import.meta.url)), "..");
const articlesPath = path.join(ROOT, "data", "articles.json");
const now = new Date().toISOString();

const EDITS = {
  "camp-fan-ranking": [
    // コツ節: 扇風機で足りない猛暑 → クーラー/ネッククーラー
    ["総合的な暑さ対策については[夏キャンプの暑さ対策ギアまとめ](/articles/summer-camp-heat-gear-guide)もあわせてどうぞ。",
     "総合的な暑さ対策については[夏キャンプの暑さ対策ギアまとめ](/articles/summer-camp-heat-gear-guide)もあわせてどうぞ。扇風機の風だけでは追いつかない猛暑日は、[ポータブルクーラー](/articles/portable-cooler-fan-guide)でテント内を冷やす、[ネッククーラー](/articles/neck-cooler-ranking)で首元を直接冷やす、といった一段上の冷却も検討する価値があります。"],
    // Q1: ポータブル電源をリンク化
    ["二泊以上のキャンプではポータブル電源+扇風機の組み合わせが安心です。",
     "二泊以上のキャンプでは[ポータブル電源](/articles/portable-power-station-guide)+扇風機の組み合わせが安心です。"],
  ],
  "summer-camp-heat-gear-guide": [
    // 柱③: 扇風機記事へ相互リンク(トップ稼ぎ頭の集客を強化)
    ["風量より静音性と稼働時間で選ぶのが正解です。",
     "風量より静音性と稼働時間で選ぶのが正解です。モデル別の比較は[キャンプ用充電式扇風機おすすめ7選](/articles/camp-fan-ranking)にまとめています。"],
    // Q3: テント内の暑さ対策 → クーラー/ネッククーラー
    ["寝る直前まで前室・出入口をメッシュにしておくだけで、就寝時の温度が変わります。",
     "寝る直前まで前室・出入口をメッシュにしておくだけで、就寝時の温度が変わります。それでも暑さが厳しい平地のサイトなら、[ポータブルクーラー](/articles/portable-cooler-fan-guide)でテント内を直接冷やす、[ネッククーラー](/articles/neck-cooler-ranking)で首元を冷やす手も効果的です。"],
    // Q4: ポータブル電源をリンク化
    ["扇風機+ポータブル電源の組み合わせは快適性への投資として十分ありです。",
     "扇風機+[ポータブル電源](/articles/portable-power-station-guide)の組み合わせは快適性への投資として十分ありです。容量の選び方はリンク先にまとめています。"],
  ],
};

const articles = JSON.parse(fs.readFileSync(articlesPath, "utf-8"));
let totalApplied = 0;
for (const [slug, edits] of Object.entries(EDITS)) {
  const a = articles.find((x) => x.slug === slug);
  if (!a) { console.log(`⚠️ 記事なし: ${slug}`); continue; }
  let applied = 0;
  for (const [from, to] of edits) {
    if (a.content.includes(to)) { console.log(`  ⏭️ 適用済み: ${slug} / ${to.slice(0, 24)}…`); continue; }
    if (a.content.includes(from)) { a.content = a.content.replace(from, to); applied++; }
    else console.log(`  ⚠️ 対象文なし: ${slug} / ${from.slice(0, 24)}…`);
  }
  if (applied) { a.updatedAt = now; totalApplied += applied; console.log(`✅ ${slug}: リンク ${applied} 箇所追加`); }
}
fs.writeFileSync(articlesPath, JSON.stringify(articles, null, 2) + "\n", "utf-8");
console.log(`\n📝 合計 ${totalApplied} 箇所。次に  npm run db:sync  で反映してください。`);
