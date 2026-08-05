#!/usr/bin/env node
/**
 * 価格の異常更新を差し戻す
 *
 * 背景（2026-08-05）: price-monitor を Creators API に移行して初回実行したところ、
 * 102件の価格を更新したが、うち12件が「半額以下」または「2倍超」の異常値だった。
 * 誤ったASIN（本体ではなくパーツや別商品を指している）が原因で、
 * 例: スノーピーク 焚火台L が ¥18,600 → ¥1,845 になっていた。
 * price-monitor は書き込み→Supabase同期→ISR再検証まで一気に走るため、
 * 誤った価格が本番に出た。これを previousPrice へ戻す。
 *
 * 判定は price-history.json の previousPrice との比率で行う。
 * 「上振れ」は登録価格が古かっただけの正しい修正であることも多いので、
 * --keep で個別に除外できるようにしてある。
 *
 * 使い方:
 *   node scripts/revert-price-anomalies.mjs                  # dry-run（既定）
 *   node scripts/revert-price-anomalies.mjs --apply          # 異常値を全部戻す
 *   node scripts/revert-price-anomalies.mjs --apply --keep light-002,burner-s-008
 *   node scripts/revert-price-anomalies.mjs --min 0.5 --max 2.0
 *
 * --apply の後は Supabase 同期が必要:
 *   npm run db:sync
 */
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const ROOT = path.join(__dirname, "..");
const PRODUCTS = path.join(ROOT, "data", "products.json");
const HISTORY = path.join(ROOT, "data", "price-history.json");

const argv = process.argv.slice(2);
const APPLY = argv.includes("--apply");
const argOf = (name, fallback) => {
  const i = argv.indexOf(name);
  return i !== -1 && argv[i + 1] ? argv[i + 1] : fallback;
};
const MIN = parseFloat(argOf("--min", "0.5"));
const MAX = parseFloat(argOf("--max", "2.0"));
const KEEP = new Set(
  (argOf("--keep", "") || "")
    .split(",")
    .map((s) => s.trim())
    .filter(Boolean)
);

if (!fs.existsSync(HISTORY)) {
  console.error(
    `price-history.json がありません（${HISTORY}）。\n` +
      "price-monitor を一度実行したマシンで動かしてください。"
  );
  process.exit(1);
}

const products = JSON.parse(fs.readFileSync(PRODUCTS, "utf8"));
const history = JSON.parse(fs.readFileSync(HISTORY, "utf8"));

const asinOf = (url) => {
  const m = (url || "").match(/\/dp\/([A-Z0-9]{10})/);
  return m ? m[1] : null;
};

// 同じASINを持つ商品が重複登録されている（焚火台L・おにやんま君など）。
// Map<asin, product> にすると片方しか拾えないので配列で持つ
const byAsin = new Map();
for (const p of products) {
  const a = asinOf(p.amazonUrl);
  if (!a) continue;
  if (!byAsin.has(a)) byAsin.set(a, []);
  byAsin.get(a).push(p);
}

const anomalies = [];
for (const [asin, h] of Object.entries(history)) {
  if (!h.price || !h.previousPrice) continue;
  const ratio = h.price / h.previousPrice;
  if (ratio >= MIN && ratio <= MAX) continue;
  for (const product of byAsin.get(asin) || []) {
    // すでに戻してある（現在価格が previousPrice と一致）ものは対象外
    if (product.price === h.previousPrice) continue;
    anomalies.push({ asin, product, ratio, from: h.price, to: h.previousPrice });
  }
}

anomalies.sort((a, b) => a.ratio - b.ratio);

console.log(
  `価格の異常更新: ${anomalies.length}件（判定レンジ ${Math.round(MIN * 100)}〜${Math.round(MAX * 100)}%）` +
    `${APPLY ? "" : " ※dry-run"}\n`
);

let reverted = 0;
for (const a of anomalies) {
  const kept = KEEP.has(a.product.id);
  const mark = kept ? "－ 据置" : APPLY ? "✓ 差戻" : "・ 対象";
  console.log(
    `${mark}  ${String(Math.round(a.ratio * 100)).padStart(4)}%  ` +
      `¥${String(a.from).padStart(7)} → ¥${String(a.to).padStart(7)}  ` +
      `${a.product.id}  ${a.product.name.slice(0, 34)}`
  );
  if (kept) continue;
  reverted++;
  if (APPLY) {
    a.product.price = a.to;
    // 次回実行で同じ差分を再検出しないよう履歴も戻す
    history[a.asin] = {
      ...history[a.asin],
      price: a.to,
      revertedAt: new Date().toISOString(),
      revertedFrom: a.from,
    };
  }
}

if (KEEP.size > 0) {
  const unknown = [...KEEP].filter((id) => !anomalies.some((a) => a.product.id === id));
  if (unknown.length) console.log(`\n⚠️ --keep に異常値でないIDが含まれています: ${unknown.join(", ")}`);
}

if (!anomalies.length) {
  console.log("差し戻す対象はありません。");
} else if (APPLY) {
  fs.writeFileSync(PRODUCTS, JSON.stringify(products, null, 2));
  fs.writeFileSync(HISTORY, JSON.stringify(history, null, 2));
  console.log(`\n✅ ${reverted}件を差し戻しました（据置 ${anomalies.length - reverted}件）`);
  console.log("次: git diff data/products.json で確認 → npm run db:sync で本番反映");
} else {
  console.log(`\ndry-run完了: ${reverted}件が差し戻し対象`);
  console.log("実行するには --apply を付けてください");
  console.log("正しい更新を残す場合は --keep <id1,id2,...> で除外できます");
}
