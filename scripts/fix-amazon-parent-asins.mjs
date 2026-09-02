#!/usr/bin/env node
/**
 * Amazonの「サイズ選択ページ」に飛んでいる商品を、子ASINに張り替える
 *
 * 背景（2026-09-02）: audit-prices が、Amazonリンクが親ASIN（バリエーション
 * 選択ページ）を指している商品を5件見つけた。読者は「3人用/4人用/6人用」の
 * 選択画面に着地して、どれを買えばいいか分からない。アメニティドームMは
 * 4記事に出ていて、記事は「Mを買え」と書いているのに、リンク先では
 * 自分でMを選ぶことになる。
 *
 * 親ASINは価格も返さないので、価格監査からも漏れ続ける。
 *
 * このスクリプトは Creators API の searchItems で子ASINの候補を探し、
 * 商品名のサイズ表記と価格の整合が取れたものだけを提案する。
 *
 * 使い方（Macで実行。Amazonの認証情報が要る）:
 *   node scripts/fix-amazon-parent-asins.mjs           # dry-run
 *   node scripts/fix-amazon-parent-asins.mjs --apply
 *   node scripts/fix-amazon-parent-asins.mjs --id tent-002   # 1件だけ
 *
 * 安全装置:
 * - 候補が親ASINらしい（「各色」「3人用/4人用」等）なら採用しない。
 *   親から親へ張り替えても意味がない
 * - products.json の specs にあるサイズ・容量の語が候補名に無ければ採用しない。
 *   アメニティドームの L を M に間違えるのが一番痛い
 * - 価格が取れない候補は採用しない。子ASINなら価格が返るはず
 * - 登録価格の 50〜200% を外れたら採用しない
 * - 迷ったらスキップして一覧に出す。誤ったサイズを掴むのは、選択ページに
 *   飛ばすより害が大きい
 */
import fs from "node:fs";
import path from "node:path";
import dns from "node:dns";
import { fileURLToPath } from "node:url";
import { loadEnv } from "../src/lib/x-agent-utils.mjs";
import {
  searchItems,
  hasCredentials,
  asinOf,
  priceOf,
  titleOf,
} from "../src/lib/amazon-creators-api.mjs";

dns.setDefaultResultOrder("ipv4first");
loadEnv();

const ROOT = path.join(path.dirname(fileURLToPath(import.meta.url)), "..");
const PRODUCTS = path.join(ROOT, "data", "products.json");
const APPLY = process.argv.includes("--apply");
const ONLY = (() => {
  const i = process.argv.indexOf("--id");
  return i > -1 ? new Set((process.argv[i + 1] ?? "").split(",")) : null;
})();

if (!hasCredentials()) {
  console.error("Amazonの認証情報がありません（.env.local を確認）。Macで実行してください");
  process.exit(1);
}

/** audit-prices と同じ判定。親から親へ張り替えないための門番 */
function looksLikeVariationParent(title) {
  const t = (title || "").normalize("NFKC");
  return (
    /各色|各サイズ|全[0-9]+色/.test(t) ||
    /[0-9]+人用\s*\/\s*[0-9]+人用/.test(t) ||
    /サイズ\s*[A-Za-z0-9+]+\s*\/\s*[A-Za-z0-9+]+/.test(t) ||
    /[0-9]+\s*[~〜]\s*[0-9]+\s*(リットル|L|cm)\b/.test(t)
  );
}

/**
 * 商品名から「サイズを決めている語」を抜く。
 * これが候補名に無ければ、別サイズを掴んでいる可能性が高い。
 * 例: アメニティドーム"M" / スペーザ ライト "250" / ジャグ "7.5L"
 */
function sizeTokens(p) {
  const out = new Set();
  const name = (p.name ?? "").normalize("NFKC");
  // 末尾や区切りの単独 S/M/L/XL
  const m = name.match(/(?:^|[\s　])(XL|[SML])(?:$|[\s　])/);
  if (m) out.add(m[1]);
  // 型番らしい英数字（3文字以上、数字を含む）
  for (const t of name.match(/[A-Z0-9][A-Z0-9-]{2,}/g) ?? []) {
    if (/\d/.test(t)) out.add(t);
  }
  // specs の容量・サイズ
  for (const key of ["容量", "capacity", "サイズ"]) {
    const v = (p.specs?.[key] ?? "").normalize("NFKC");
    const n = v.match(/([\d.]+)\s*(L|リットル)/i);
    if (n) out.add(n[1]);
  }
  return [...out];
}

const raw = JSON.parse(fs.readFileSync(PRODUCTS, "utf8"));
const products = Array.isArray(raw) ? raw : raw.products;

// 対象は明示指定か、Amazonリンクがあって親らしい名前の商品。
// 親判定は audit-prices が持っているので、ここでは登録名から探さず
// --id で渡してもらうのを基本にする
const DEFAULT_TARGETS = [
  "tent-002",
  "growler-001",
  "cooler-004",
  "water-jug-stanley-7.5l",
];
const targetIds = ONLY ?? new Set(DEFAULT_TARGETS);
const targets = products.filter((p) => targetIds.has(p.id) && p.amazonUrl);

console.log(`対象 ${targets.length}件${APPLY ? "（APPLY）" : "（dry-run）"}\n`);

const proposals = [];
const skipped = [];

for (const p of targets) {
  const tokens = sizeTokens(p);
  const keyword = `${p.brand ?? ""} ${p.name}`.trim();
  console.log(`── ${p.id}  ${p.name}`);
  console.log(`   現ASIN: ${asinOf(p.amazonUrl)} / サイズ語: ${tokens.join(", ") || "（無し）"}`);

  let items;
  try {
    items = await searchItems(keyword, { itemCount: 10 });
  } catch (e) {
    console.log(`   ✗ 検索失敗: ${String(e.message).slice(0, 100)}`);
    skipped.push({ id: p.id, reason: `検索失敗: ${e.message}` });
    continue;
  }

  const scored = [];
  for (const it of items) {
    const asin = it.asin ?? it.ASIN;
    const title = titleOf(it);
    const price = priceOf(it);
    const reasons = [];
    if (!asin || asin === asinOf(p.amazonUrl)) reasons.push("同じASIN");
    if (looksLikeVariationParent(title)) reasons.push("これも選択ページ");
    if (price == null) reasons.push("価格が返らない");
    // サイズ語が1つも含まれないなら別サイズの疑い
    if (tokens.length > 0 && !tokens.some((t) => title.normalize("NFKC").includes(t)))
      reasons.push(`サイズ語（${tokens.join("/")}）を含まない`);
    if (price != null && p.price) {
      const ratio = price / p.price;
      if (ratio < 0.5 || ratio > 2) reasons.push(`価格が登録の${Math.round(ratio * 100)}%`);
    }
    scored.push({ asin, title, price, reasons });
  }

  const ok = scored.filter((s) => s.reasons.length === 0);
  if (ok.length === 1) {
    const c = ok[0];
    console.log(`   ✅ ${c.asin}  ¥${c.price?.toLocaleString()}  ${c.title.slice(0, 56)}`);
    proposals.push({ id: p.id, asin: c.asin, title: c.title, price: c.price });
  } else if (ok.length > 1) {
    console.log(`   ✗ 候補が${ok.length}件あって絞れない。目視してください:`);
    for (const c of ok) console.log(`      ${c.asin}  ¥${c.price?.toLocaleString()}  ${c.title.slice(0, 52)}`);
    skipped.push({ id: p.id, reason: `候補${ok.length}件`, candidates: ok });
  } else {
    console.log(`   ✗ 条件を満たす候補なし。上位3件と却下理由:`);
    for (const c of scored.slice(0, 3))
      console.log(`      ${c.asin ?? "-"}  ${c.title.slice(0, 44)}\n         → ${c.reasons.join(" / ")}`);
    skipped.push({ id: p.id, reason: "候補なし", candidates: scored.slice(0, 3) });
  }
  console.log();
  await new Promise((r) => setTimeout(r, 1500)); // API の連打を避ける
}

console.log(`── まとめ ──`);
console.log(`  張り替え提案: ${proposals.length}件 / 目視が要る: ${skipped.length}件`);

if (proposals.length === 0 || !APPLY) {
  if (proposals.length > 0) console.log("\ndry-run です。--apply で書き込みます");
  process.exit(0);
}

const now = new Date().toISOString();
for (const { id, asin } of proposals) {
  const p = products.find((x) => x.id === id);
  p.amazonUrl = `https://www.amazon.co.jp/dp/${asin}/?tag=camp78-22`;
  // updatedAt を進めないと db:sync で反映されない
  p.updatedAt = now;
}
fs.writeFileSync(PRODUCTS, JSON.stringify(products, null, 2) + "\n");
console.log(`\n${proposals.length}件の amazonUrl を張り替えました`);
console.log("次: npm run data:normalize && git diff で確認");
