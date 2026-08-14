#!/usr/bin/env node
/**
 * Amazonリンクを外して除外リストに登録する
 *
 * 背景（2026-08-14）: リンク検証で見つかった誤リンクのうち、調べ直しても
 * 正しいASINが出てこないものがある。DARCHE のように日本のAmazonに流通が
 * 無いブランドが典型で、放っておくと照合のたびに別ブランドの近い商品を
 * 掴みに行く（実際 tarp-008 は XiaZ の日除けシェードを指していた）。
 *
 * 誤ったリンクは、リンクが無い状態より害が大きい。読者は別の商品のページに
 * 着地し、こちらは成果にならない。楽天リンクが生きているなら、Amazonは
 * 空にして楽天ボタンだけ残すのが正しい。
 *
 * 除外リストにも同時に登録する。そうしないと次の照合でまた同じ商品を
 * 掴み直してしまう（--ids で明示指定すれば除外を無視して調べ直せる）。
 *
 * 使い方:
 *   node scripts/clear-amazon-link.mjs --ids tarp-008 --reason "日本のAmazonに流通が無い"
 *   node scripts/clear-amazon-link.mjs --ids a,b --reason "..." --apply
 *
 * --apply を付けるまでは何も書き換えない。
 * 実行後は npm run db:sync -- --no-pull で反映すること。
 */
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const ROOT = path.join(__dirname, "..");
const PRODUCTS = path.join(ROOT, "data", "products.json");
const EXCLUSIONS = path.join(ROOT, "data", "amazon-match-exclusions.json");

const argv = process.argv.slice(2);
const argVal = (name) => {
  const i = argv.indexOf(name);
  return i !== -1 ? argv[i + 1] : null;
};
const APPLY = argv.includes("--apply");
const IDS = (argVal("--ids") || "").split(",").map((s) => s.trim()).filter(Boolean);
const REASON = argVal("--reason") || "";

if (IDS.length === 0) {
  console.error("--ids で対象を指定してください（カンマ区切り）");
  process.exit(1);
}
if (!REASON) {
  console.error("--reason で理由を書いてください。除外リストは理由が無いと後から判断できません");
  process.exit(1);
}

const products = JSON.parse(fs.readFileSync(PRODUCTS, "utf8"));
const exclusions = JSON.parse(fs.readFileSync(EXCLUSIONS, "utf8"));
const already = new Set((exclusions.exclusions || []).map((e) => e.id));

const now = new Date().toISOString();
let changed = 0;
let addedExclusions = 0;

for (const id of IDS) {
  const p = products.find((x) => x.id === id);
  if (!p) {
    console.log(`✗ ${id}: 商品が見つかりません`);
    continue;
  }
  const hadAmazon = Boolean(p.amazonUrl);
  const hasRakuten = Boolean(p.affiliateUrl);
  console.log(`\n${id}  ${p.name}`);
  console.log(`   Amazon: ${hadAmazon ? p.amazonUrl.slice(0, 60) : "(すでに空)"}`);
  console.log(`   楽天  : ${hasRakuten ? "あり" : "なし"}`);
  if (!hasRakuten) {
    // 両方空にすると商品カードから買う手段が消える。事故になるので止める
    console.log("   ⚠ 楽天リンクもありません。Amazonを空にすると買う導線が消えるのでスキップします");
    continue;
  }
  if (hadAmazon && APPLY) {
    p.amazonUrl = "";
    p.updatedAt = now; // pull時のマージ巻き戻し防止
  }
  if (hadAmazon) changed++;
  if (!already.has(id)) {
    if (APPLY) exclusions.exclusions.push({ id, reason: REASON });
    addedExclusions++;
  }
  console.log(`   → Amazonリンクを空にし、除外リストに登録${APPLY ? "" : "（予定）"}`);
}

console.log(`\n── ${APPLY ? "適用" : "dry-run"} ──`);
console.log(`  Amazonリンクを外す: ${changed}件`);
console.log(`  除外リストに追加  : ${addedExclusions}件`);

if (!APPLY) {
  console.log("\n書き換えるには --apply");
  process.exit(0);
}

fs.writeFileSync(PRODUCTS, JSON.stringify(products, null, 2));
exclusions._updatedAt = now.slice(0, 10);
fs.writeFileSync(EXCLUSIONS, JSON.stringify(exclusions, null, 2));
console.log("\ndata/products.json と data/amazon-match-exclusions.json を更新しました");
console.log("反映: npm run db:sync -- --no-pull");
