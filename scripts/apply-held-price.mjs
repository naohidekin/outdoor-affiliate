#!/usr/bin/env node
/**
 * price-monitor がガードで保留した価格を、目視確認のうえ個別に適用する
 *
 * price-monitor は変動率が大きい更新（既定 0.5〜2.0倍の外）を自動適用せず
 * data/price-held-back.json に書き出す。誤ったASIN（本体ではなくパーツ）を
 * 指している場合と、単に登録価格が古かった場合の両方があるため、
 * Amazonのページを開いて確認してから適用する運用にしている。
 *
 * 使い方:
 *   node scripts/apply-held-price.mjs                    # 保留一覧を表示
 *   node scripts/apply-held-price.mjs fp-006 chair-011   # 指定IDを適用
 *   node scripts/apply-held-price.mjs --all              # 全件適用（非推奨）
 *
 * 適用後は同期が必要:
 *   npm run db:sync -- --no-pull
 */
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const ROOT = path.join(__dirname, "..");
const DATA = path.join(ROOT, "data");
const PRODUCTS = path.join(DATA, "products.json");
const HELD = path.join(DATA, "price-held-back.json");
const HISTORY = path.join(DATA, "price-history.json");

if (!fs.existsSync(HELD)) {
  console.error(`保留一覧がありません（${HELD}）。先に price-monitor を実行してください。`);
  process.exit(1);
}

const held = JSON.parse(fs.readFileSync(HELD, "utf8"));
const items = held.items || [];
const argv = process.argv.slice(2);
const ALL = argv.includes("--all");
const targetIds = new Set(argv.filter((a) => !a.startsWith("--")));

if (!ALL && targetIds.size === 0) {
  console.log(`保留中の価格更新: ${items.length}件（検出 ${held.checkedAt}）\n`);
  for (const h of items) {
    console.log(
      `${String(Math.round(h.ratio * 100)).padStart(4)}%  ¥${String(h.prevPrice).padStart(7)} → ¥${String(h.currentPrice).padStart(7)}  ${h.name.slice(0, 34)}`
    );
    console.log(`        ID: ${h.ids.join(", ")}`);
    console.log(`        ${h.amazonUrl}\n`);
  }
  console.log("適用: node scripts/apply-held-price.mjs <商品ID> [<商品ID>...]");
  console.log("※ 先にURLを開き、本体を指しているか確認してください");
  process.exit(0);
}

const products = JSON.parse(fs.readFileSync(PRODUCTS, "utf8"));
const history = fs.existsSync(HISTORY) ? JSON.parse(fs.readFileSync(HISTORY, "utf8")) : {};

const applied = [];
const remaining = [];
for (const h of items) {
  const hit = ALL || h.ids.some((id) => targetIds.has(id));
  if (!hit) {
    remaining.push(h);
    continue;
  }
  // 同じASINの商品はまとめて更新する（重複登録があるため）
  for (const id of h.ids) {
    const p = products.find((q) => q.id === id);
    if (!p) {
      console.log(`⚠️ 未検出: ${id}`);
      continue;
    }
    const ts = new Date().toISOString();
    console.log(`✓ ${id}  ¥${p.price} → ¥${h.currentPrice}  ${p.name.slice(0, 30)}`);
    p.price = h.currentPrice;
    p.priceUpdatedAt = ts;
    // updatedAt を進めないと sync の auto-pull で巻き戻る
    p.updatedAt = ts;
  }
  history[h.asin] = {
    price: h.currentPrice,
    previousPrice: h.prevPrice,
    checkedAt: new Date().toISOString(),
    approvedManually: true,
  };
  applied.push(h);
}

const unknown = [...targetIds].filter(
  (id) => !items.some((h) => h.ids.includes(id))
);
if (unknown.length) console.log(`\n⚠️ 保留一覧にないID: ${unknown.join(", ")}`);

if (applied.length === 0) {
  console.log("適用対象がありません。");
  process.exit(0);
}

fs.writeFileSync(PRODUCTS, JSON.stringify(products, null, 2));
fs.writeFileSync(HISTORY, JSON.stringify(history, null, 2));
fs.writeFileSync(
  HELD,
  JSON.stringify({ ...held, items: remaining }, null, 2)
);

console.log(`\n✅ ${applied.length}件を適用しました（保留残り ${remaining.length}件）`);
console.log("次: npm run db:sync -- --no-pull で本番反映");
