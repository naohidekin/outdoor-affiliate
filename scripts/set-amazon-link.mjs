#!/usr/bin/env node
/**
 * 目視で確認したASINを手で設定する
 *
 * 背景（2026-08-14）: 自動照合の価格ゲートは、候補の選抜段階で落とす。
 * 落ちたものは提案自体が作られないので、--only では拾えない。これは
 * 設計として正しい（付属品や別グレードを掴む事故の防波堤になっている）。
 *
 * ただし人間のほうが強い根拠を持っている場合がある。tarp-007 がそれで、
 * Amazonのタイトルに入っている 74175042 は LOGOS の品番で、登録済みの
 * 楽天リンク 7dials/7d74175042 と同じ番号だった。品番が一致している以上、
 * 価格差は「モールによって売値が違う」だけの話で、別商品ではない。
 *
 * そこでゲートを緩めるのではなく、**人間の確認をゲートの代わりに置く**
 * 経路を用意する。緩めると全商品に効いてしまうが、これは1件ずつ効く。
 *
 * 書き込む前に、そのASINの実物（タイトル・価格・ブランド一致・一致率）を
 * 必ず表示する。番号を打ち間違えたまま適用する事故を防ぐため。
 *
 * 使い方:
 *   node scripts/set-amazon-link.mjs --id tarp-007 --asin B08L5ZQMR1
 *   node scripts/set-amazon-link.mjs --id tarp-007 --asin B08L5ZQMR1 --apply
 *
 * --apply を付けるまでは何も書き換えない。
 * 実行後は npm run db:sync -- --no-pull で反映すること。
 */
import fs from "node:fs";
import path from "node:path";
import dns from "node:dns";
import { fileURLToPath } from "node:url";
import { loadEnv } from "../src/lib/x-agent-utils.mjs";
import { getItems, hasCredentials, credentials, priceOf, titleOf } from "../src/lib/amazon-creators-api.mjs";
import { tokenOverlap, brandMatches, normalizeBrands } from "../src/lib/product-match.mjs";

dns.setDefaultResultOrder("ipv4first");
loadEnv();

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const ROOT = path.join(__dirname, "..");
const PRODUCTS = path.join(ROOT, "data", "products.json");

const argv = process.argv.slice(2);
const argVal = (n) => {
  const i = argv.indexOf(n);
  return i !== -1 && argv[i + 1] ? argv[i + 1] : null;
};
const APPLY = argv.includes("--apply");
const ID = argVal("--id");
const ASIN = (argVal("--asin") || "").toUpperCase();

if (!ID || !ASIN) {
  console.error("使い方: node scripts/set-amazon-link.mjs --id <商品ID> --asin <ASIN> [--apply]");
  process.exit(1);
}
if (!/^[A-Z0-9]{10}$/.test(ASIN)) {
  console.error(`ASINの形式が違います: ${ASIN}（英数10桁）`);
  process.exit(1);
}
if (!hasCredentials()) {
  console.error("Amazon Creators API の認証情報がありません（.env.local を確認）");
  console.error("実物を確認せずに書き込むことはしません");
  process.exit(1);
}

const products = JSON.parse(fs.readFileSync(PRODUCTS, "utf8"));
const p = products.find((x) => x.id === ID);
if (!p) {
  console.error(`商品が見つかりません: ${ID}`);
  process.exit(1);
}

const items = await getItems([ASIN]);
const item = items[0];
if (!item) {
  console.error(`ASIN ${ASIN} がAmazonで引けません。番号が違うか、取り扱いが終わっています`);
  process.exit(1);
}

const title = titleOf(item) || "";
const price = priceOf(item);
const norm = (s) => normalizeBrands((s || "").normalize("NFKC").toLowerCase());
const overlap = tokenOverlap(norm(p.name), norm(title));
const brandOk = brandMatches(p.brand, title);
const ratio = p.price && price ? price / p.price : null;

console.log(`\n${p.id}  ${p.name}`);
console.log(`   登録: ブランド「${p.brand || "(なし)"}」 / 価格 ¥${(p.price || 0).toLocaleString()}`);
console.log(`   現在のAmazonリンク: ${p.amazonUrl || "(なし)"}`);
console.log(`\n   → ${ASIN}`);
console.log(`     「${title}」`);
console.log(
  `     価格 ${price ? `¥${price.toLocaleString()}` : "(取得できず)"}` +
    (ratio ? `（登録価格の${Math.round(ratio * 100)}%）` : "")
);
console.log(`     一致率 ${Math.round(overlap * 100)}% / ブランド${brandOk ? "一致" : "不一致"}`);

// 自動照合が落とす条件をそのまま表示する。人間が上書きしていることを自覚するため
const warnings = [];
if (!brandOk) warnings.push("ブランドがタイトルに出てきません");
if (overlap < 0.5) warnings.push(`一致率が低いです（${Math.round(overlap * 100)}%）`);
if (ratio && (ratio < 0.6 || ratio > 2.0)) warnings.push(`価格が登録の60〜200%の外です（${Math.round(ratio * 100)}%）`);
if (warnings.length) {
  console.log(`\n   ⚠ 自動照合ならここで止まります:`);
  for (const w of warnings) console.log(`     ・${w}`);
  console.log(`   それでも正しいと判断した場合だけ --apply してください`);
}

if (!APPLY) {
  console.log("\n書き換えるには --apply");
  process.exit(0);
}

p.amazonUrl = `https://www.amazon.co.jp/dp/${ASIN}/?tag=${credentials().partnerTag}`;
p.updatedAt = new Date().toISOString(); // pull時のマージ巻き戻し防止
fs.writeFileSync(PRODUCTS, JSON.stringify(products, null, 2));
console.log(`\n${p.id} の amazonUrl を ${ASIN} に設定しました`);
console.log("反映: npm run db:sync -- --no-pull");
