#!/usr/bin/env node
/**
 * Amazon ASIN を products.json に登録する
 *
 * 背景（2026-08-03）: 秋冬P1で追加した暖房6製品は楽天リンクだけが入っており、
 * amazonUrl が空。ASINはAPIでは取れず（PA-APIは検索精度が低く別商品を掴む）、
 * 商品ページのURLを見るのが一番確実なので、手で貼る前提の道具にした。
 *
 * ## ASINの調べ方
 * 1. https://www.amazon.co.jp/ で商品名（型番があれば型番）で検索
 * 2. 商品ページを開き、URLの `/dp/` の直後10桁を見る
 *      https://www.amazon.co.jp/dp/B0CYT9N94T/...
 *                                  ~~~~~~~~~~ これがASIN
 *    `/dp/` が無いURLなら、ページ下部の「登録情報」にもASINが載っている
 * 3. 型番・容量・色まで一致しているか必ず確認する（別モデルを掴むと誤誘導になる）
 *
 * ## 使い方
 *   node scripts/set-amazon-asin.mjs --list                     # 未設定の商品を出す
 *   node scripts/set-amazon-asin.mjs id=ASIN id=ASIN            # 検証のみ
 *   node scripts/set-amazon-asin.mjs id=ASIN --apply            # 反映
 *
 * 商品ページのURLをそのまま貼ってもASINを抜き出す:
 *   node scripts/set-amazon-asin.mjs 'heater-corona-fh-cpf25a=https://www.amazon.co.jp/dp/B0XXXXXXXX/ref=...'
 */
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const PRODUCTS = path.join(__dirname, "..", "data", "products.json");
const TAG = process.env.AMAZON_PARTNER_TAG || "camp78-22";

const APPLY = process.argv.includes("--apply");
const LIST = process.argv.includes("--list");

const products = JSON.parse(fs.readFileSync(PRODUCTS, "utf8"));
const byId = new Map(products.map((p) => [p.id, p]));

// 「Amazon主導線」の閾値。これ以上の価格帯はASINが無いと取りこぼしが大きい
// （楽天は1件¥1,000で頭打ち。src/lib/affiliate-priority.ts と同じ値）
const AMAZON_PRIMARY_PRICE = 33000;

if (LIST) {
  const missing = products.filter((p) => !p.amazonUrl || !/\/dp\//.test(p.amazonUrl));
  missing.sort((a, b) => (b.price || 0) - (a.price || 0));
  console.log(`\nAmazon商品リンクが未設定: ${missing.length}件（価格の高い順）\n`);
  for (const p of missing.slice(0, 40)) {
    const urgent = (p.price || 0) >= AMAZON_PRIMARY_PRICE ? " ★Amazon主導線" : "";
    const q = encodeURIComponent(p.name.slice(0, 80));
    console.log(`${p.id}`);
    console.log(`   ${p.name}  ¥${(p.price || 0).toLocaleString()}${urgent}`);
    console.log(`   検索: https://www.amazon.co.jp/s?k=${q}`);
    if (p.amazonUrl) console.log(`   現在: ${p.amazonUrl.slice(0, 90)}`);
    console.log();
  }
  if (missing.length > 40) console.log(`（ほか ${missing.length - 40}件）`);
  process.exit(0);
}

// ASINは10桁の英数字。B0で始まる現行品が大半だが、書籍等は数字のみのISBNもある
function extractAsin(value) {
  const v = (value || "").trim();
  const fromUrl = v.match(/\/(?:dp|gp\/product|gp\/aw\/d)\/([A-Z0-9]{10})/i);
  if (fromUrl) return fromUrl[1].toUpperCase();
  if (/^[A-Z0-9]{10}$/i.test(v)) return v.toUpperCase();
  return null;
}

const pairs = process.argv.slice(2).filter((a) => a.includes("=") && !a.startsWith("--"));
if (pairs.length === 0) {
  console.error(
    "指定がありません。\n" +
      "  node scripts/set-amazon-asin.mjs --list\n" +
      "  node scripts/set-amazon-asin.mjs 商品ID=ASIN [商品ID=ASIN ...] [--apply]"
  );
  process.exit(1);
}

const ok = [];
const errors = [];
for (const pair of pairs) {
  const idx = pair.indexOf("=");
  const id = pair.slice(0, idx).trim();
  const raw = pair.slice(idx + 1).trim();
  const p = byId.get(id);
  if (!p) {
    errors.push(`${id}: products.json に存在しません`);
    continue;
  }
  const asin = extractAsin(raw);
  if (!asin) {
    errors.push(`${id}: ASINとして読めません → ${raw.slice(0, 60)}`);
    continue;
  }
  // 検索URLが貼られた場合を弾く（/s?k= は商品ページではない）
  if (/\/s\?|\/s\//.test(raw)) {
    errors.push(`${id}: 検索ページのURLです。商品ページ（/dp/）を開いてください`);
    continue;
  }
  const url = `https://www.amazon.co.jp/dp/${asin}?tag=${TAG}`;
  ok.push({ p, asin, url, before: p.amazonUrl || "(なし)" });
}

console.log("\n=== ASIN登録 ===\n");
for (const o of ok) {
  console.log(`■ ${o.p.name}（¥${(o.p.price || 0).toLocaleString()}）`);
  console.log(`   前: ${o.before.slice(0, 80)}`);
  console.log(`   後: ${o.url}`);
  if ((o.p.price || 0) >= AMAZON_PRIMARY_PRICE) {
    console.log(`   → この価格帯はAmazonが主導線になります`);
  }
  console.log();
}
if (errors.length) {
  console.log("▼ エラー");
  for (const e of errors) console.log(`  - ${e}`);
  console.log();
}

if (!APPLY) {
  console.log(`${ok.length}件を登録できます。反映するには --apply を付けてください。`);
  process.exit(errors.length ? 1 : 0);
}
if (errors.length) {
  console.error("エラーがあるため反映しません。修正してから再実行してください。");
  process.exit(1);
}

const now = new Date().toISOString();
for (const o of ok) {
  o.p.amazonUrl = o.url;
  o.p.updatedAt = now;
}
fs.writeFileSync(PRODUCTS, JSON.stringify(products, null, 2) + "\n");
console.log(`${ok.length}件を products.json に書き込みました。`);
console.log("Supabaseへ反映するには: npm run db:sync");
