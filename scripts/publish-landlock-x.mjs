#!/usr/bin/env node

/**
 * snow-peak-landlock-x-review を発売後向けに微修正して公開する。
 * 内容はフルリライト不要（高品質・スペックは公式一致確認済み）。
 *  1. 発売前提の時制を発売後に更新（3箇所）
 *  2. 末尾の「アフィリンクは後で追加予定」を実態に合わせて修正（比較表に既にリンクあり）
 *  3. ヒーロー商品カードを2箇所に追加（価格納得の直後＋まとめ）
 *  4. status=published / publishedAt / updatedAt を設定して公開
 * 使い方: node scripts/publish-landlock-x.mjs  →  npm run db:sync
 * ※ 冪等
 */

import fs from "fs";
import path from "path";
import { fileURLToPath } from "url";

const ROOT = path.join(path.dirname(fileURLToPath(import.meta.url)), "..");
const articlesPath = path.join(ROOT, "data", "articles.json");
const now = new Date().toISOString();
const CARD = "{{product:tent-f-landlock-x}}";

const REPLACEMENTS = [
  // 1. 冒頭: 発売済みであることを明確化
  [
    "発売日は2026年6月27日。僕はまだ実機を手にしていないため、本記事は公式スペック・プレスリリース・メディアレビュー（GARVY+等）をベースに書いています。入手次第、設営時間の実測・居住性・結露量のデータを追記する予定です。その点はご了承ください。",
    "発売日は2026年6月27日で、すでに発売されています。ただ僕はまだ実機を手にしていないため、本記事は公式スペック・プレスリリース・メディアレビュー（GARVY+等）をベースに書いています。入手次第、設営時間の実測・居住性・結露量のデータを追記していきます。その点はご了承ください。",
  ],
  // 2. 買い替え章: 「発売を前に」→「発売後」
  [
    "2026年6月27日の発売を前に、もっとも多い質問がこれです。",
    "2026年6月27日の発売後、もっとも多い質問がこれです。",
  ],
  // 3. Q3: 現時点を7月に
  [
    "スノーピーク公式からの廃番アナウンスは現時点（2026年6月）ではありません。",
    "スノーピーク公式からの廃番アナウンスは現時点（2026年7月）ではありません。",
  ],
  // 4. 価格納得の直後にヒーローカード
  [
    "月2,000円程度で最上位クラスの2ルームシェルターが使えると考えると、長期使用視点では十分に合理的な判断です。",
    "月2,000円程度で最上位クラスの2ルームシェルターが使えると考えると、長期使用視点では十分に合理的な判断です。\n\n" + CARD,
  ],
  // 5. まとめ末尾: 陳腐化した「後で追加予定」文をCTAに置換＋カード
  [
    "アフィリエイトリンクは発売後・実機確認の上で追加する予定です。気になる方は2026年7月以降にもう一度チェックしてみてください。",
    "実機での使用レビューは入手後に追記していきますが、スペック面での進化はこの記事で出そろっています。最新の価格・在庫は下のリンクから確認できます。\n\n" + CARD,
  ],
];

const articles = JSON.parse(fs.readFileSync(articlesPath, "utf-8"));
const a = articles.find((x) => x.slug === "snow-peak-landlock-x-review");
if (!a) { console.error("❌ 記事なし: snow-peak-landlock-x-review"); process.exit(1); }

let applied = 0, skipped = 0;
for (const [from, to] of REPLACEMENTS) {
  if (a.content.includes(to)) { skipped++; console.log(`  ⏭️ 適用済: ${from.slice(0, 22)}…`); continue; }
  if (!a.content.includes(from)) { console.log(`  ⚠️ 対象文なし: ${from.slice(0, 22)}…`); continue; }
  a.content = a.content.replace(from, to);
  applied++;
  console.log(`✅ 更新: ${from.slice(0, 22)}…`);
}

// 公開状態に
const wasPublished = a.status === "published";
a.status = "published";
if (!a.publishedAt) a.publishedAt = now;
a.updatedAt = now;

const cards = (a.content.match(/\{\{product:[^}]+\}\}/g) || []).length;
const cmp = (a.content.match(/\{\{comparison:[^}]+\}\}/g) || []).length;
console.log(`\n状態: status=${a.status}${wasPublished ? "" : "（draft→published）"} / publishedAt=${a.publishedAt}`);
console.log(`収益化: 商品カード ${cards} 枚 / 比較表 ${cmp} 個`);
console.log(`本文修正: 適用 ${applied} / 既存 ${skipped}`);

fs.writeFileSync(articlesPath, JSON.stringify(articles, null, 2) + "\n", "utf-8");
console.log(`\n📝 保存完了。次に  npm run db:sync  で公開反映してください。`);
