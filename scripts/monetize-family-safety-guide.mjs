#!/usr/bin/env node

/**
 * family-camp-safety-guide（8,300字・商品0）を収益化。
 * 6大リスクの各セクション解説文の直後（関連記事ブロックの前）に、
 * 文脈に合う既存ブランド品カードを挿入する。押しつけない自然な導線。
 * 商品は全て affiliateUrl 設定済み。productIds も記事に登録する。
 * 使い方: node scripts/monetize-family-safety-guide.mjs  →  npm run db:sync
 * ※ 冪等
 */

import fs from "fs";
import path from "path";
import { fileURLToPath } from "url";

const ROOT = path.join(path.dirname(fileURLToPath(import.meta.url)), "..");
const articlesPath = path.join(ROOT, "data", "articles.json");
const now = new Date().toISOString();

// [解説文末尾(アンカー), リード文, [productId,...]]
const INSERTS = [
  [
    "噛まれているのを見つけた場合は、無理に引っ張らず皮膚科か外科を受診してください。",
    "僕が家族キャンプで実際に使っている虫対策グッズを挙げておきます。小さな子には薬剤の少ないタイプが安心です。",
    ["insect-repellent-011", "insect-repellent-003"],
  ],
  [
    "汗をかいた分だけ塩分も失われるため、経口補水液やスポーツドリンクを準備しておくと安心です。",
    "首を冷やす道具と、暑さを数値で見張る道具。この3つが子連れの夏キャンプで効きます。",
    ["neck-suo-ring", "neck-mizuno-cooling-towel", "heatstroke-wbgt-meter"],
  ],
  [
    "「日中暖かかったから」という油断が、夜中に子どもを震えさせます。",
    "子ども用シュラフは「洗える」「快適温度に余裕がある」で選ぶと失敗しません。",
    ["sb-kids-001", "sb-kids-003"],
  ],
  [
    "手洗い、肉の十分な加熱、調理器具の清潔さ。この3つがキャンプ場でも変わらぬ基本です。",
    "保冷力で選ぶなら、この2つは家族分の食材管理を安心して任せられます。",
    ["cooler-001", "cooler-004"],
  ],
  [
    "「備えとしての3,000円」として、テント泊の全装備の中で最も費用対効果が高いギアのひとつだと思っています。",
    "僕が信頼して使っているCOチェッカーはこのあたりです。命に関わる部分なので、ここはケチらないでほしいところ。",
    ["co-detector-coalan-cl715", "co-detector-dod-cg1559"],
  ],
  [
    "顔・手・股間・関節部など特定部位のやけどは、医療機関を受診してください。",
    "やけどの応急処置用に、湿潤ドレッシング材を救急ポーチに入れておくと安心です。",
    ["first-aid-burn-aid"],
  ],
  [
    "その後、抗ヒスタミン薬の塗り薬を使用してください。",
    "毒の吸い出しとマダニ除去は、専用の道具があると現地で慌てません。",
    ["first-aid-poison-remover", "first-aid-tick-remover"],
  ],
];

const articles = JSON.parse(fs.readFileSync(articlesPath, "utf-8"));
const a = articles.find((x) => x.slug === "family-camp-safety-guide");
if (!a) { console.error("❌ 記事なし: family-camp-safety-guide"); process.exit(1); }

let inserted = 0;
const allPids = [];
for (const [anchor, lead, pids] of INSERTS) {
  allPids.push(...pids);
  const cards = pids.map((p) => `{{product:${p}}}`).join("\n\n");
  if (pids.every((p) => a.content.includes(`{{product:${p}}}`))) { console.log(`  ⏭️ 既存: ${anchor.slice(0, 18)}…`); continue; }
  if (!a.content.includes(anchor)) { console.log(`  ⚠️ アンカー無し: ${anchor.slice(0, 24)}…`); continue; }
  a.content = a.content.replace(anchor, `${anchor}\n\n${lead}\n\n${cards}`);
  inserted += pids.length;
  console.log(`✅ 挿入(${pids.length}枚): ${anchor.slice(0, 18)}…`);
}

// productIds を記事に登録（重複排除）
const merged = Array.from(new Set([...(a.productIds || []), ...allPids]));
const pidChanged = JSON.stringify(merged) !== JSON.stringify(a.productIds || []);
if (pidChanged) a.productIds = merged;

if (inserted || pidChanged) {
  a.updatedAt = now;
  fs.writeFileSync(articlesPath, JSON.stringify(articles, null, 2) + "\n", "utf-8");
  console.log(`\n📝 カード ${inserted} 枚挿入 / productIds ${merged.length} 件登録`);
} else {
  console.log("\n📝 変更なし（適用済み）");
}
console.log("次に  npm run db:sync  で反映してください。");
