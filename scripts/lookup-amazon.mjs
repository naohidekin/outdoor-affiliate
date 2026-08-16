#!/usr/bin/env node
/**
 * AmazonのASIN・検索結果を素で見る
 *
 * 背景（2026-08-14）: 照合スクリプトが検索で見つけたASIN（B08L5ZQMR1）を
 * set-amazon-link.mjs の getItems で引くと「引けません」になった。
 * 検索には出るのに個別取得できないASINがあるらしく、切り分けに素の
 * 問い合わせが要る。毎回 node -e で書くと loadEnv() を忘れて
 * 「認証情報がありません」に化ける（実際そうなった）。
 *
 * 何も書き換えない。見るだけ。
 *
 * 使い方:
 *   node scripts/lookup-amazon.mjs --asin B08L5ZQMR1
 *   node scripts/lookup-amazon.mjs --asin B08L5ZQMR1,B0CL6GFW6Q
 *   node scripts/lookup-amazon.mjs --search "ロゴス USBシェードランタン 4連タイプ"
 *   node scripts/lookup-amazon.mjs --product tarp-007   # 商品名で検索し現リンクも引く
 *   node scripts/lookup-amazon.mjs --asin B0XXXX --raw  # APIの応答をそのまま出す
 */
import fs from "node:fs";
import path from "node:path";
import dns from "node:dns";
import { fileURLToPath } from "node:url";
import { loadEnv } from "../src/lib/x-agent-utils.mjs";
import {
  getItems,
  searchItems,
  hasCredentials,
  priceOf,
  titleOf,
  asinOf,
} from "../src/lib/amazon-creators-api.mjs";

dns.setDefaultResultOrder("ipv4first");
loadEnv();

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const ROOT = path.join(__dirname, "..");

const argv = process.argv.slice(2);
const argVal = (n) => {
  const i = argv.indexOf(n);
  return i !== -1 && argv[i + 1] ? argv[i + 1] : null;
};
const RAW = argv.includes("--raw");

if (!hasCredentials()) {
  console.error("Creators API の認証情報がありません（.env.local を確認）");
  process.exit(1);
}

const show = (it) =>
  console.log(
    `  ${it.asin}  ${priceOf(it) ? `¥${String(priceOf(it)).padStart(7)}` : "  価格なし"}  ` +
      `${(titleOf(it) || "(タイトルなし)").slice(0, 62)}`
  );

let asins = (argVal("--asin") || "").split(",").map((s) => s.trim().toUpperCase()).filter(Boolean);
let query = argVal("--search");

const productId = argVal("--product");
if (productId) {
  const products = JSON.parse(fs.readFileSync(path.join(ROOT, "data", "products.json"), "utf8"));
  const p = products.find((x) => x.id === productId);
  if (!p) {
    console.error(`商品が見つかりません: ${productId}`);
    process.exit(1);
  }
  console.log(`\n${p.id}  ${p.name}`);
  console.log(`  ブランド「${p.brand || "(なし)"}」 / 登録価格 ¥${(p.price || 0).toLocaleString()}`);
  query = query || `${p.brand || ""} ${p.name}`.replace(/[（(].*?[)）]/g, " ").trim();
  const cur = asinOf(p.amazonUrl);
  if (cur && !asins.includes(cur)) asins.push(cur);
}

if (asins.length) {
  console.log(`\n── ASIN直引き（${asins.length}件）──`);
  // getItems は配列ではなく { items, errors } を返す
  const { items, errors } = await getItems(asins);
  const got = new Set(items.map((it) => it.asin));
  for (const it of items) show(it);
  // 「引けなかった」を黙って落とさない。切り分けたいのはまさにそこ
  for (const a of asins) if (!got.has(a)) console.log(`  ${a}  ← 個別取得できません`);
  for (const e of errors) console.log(`  APIエラー: ${e.code || ""} ${e.message || JSON.stringify(e)}`);

  // 価格が取れない理由を調べるための素の応答。
  // 2026-08-16: 全件監査で309件中133件（44%）に価格が無かった。
  // 在庫切れなのか offersV2 の形が想定と違うのかは、応答を見ないと分からない
  if (RAW) {
    for (const it of items) {
      console.log(`\n  ── ${it.asin} の応答 ──`);
      console.log(JSON.stringify(it, null, 2).split("\n").map((l) => "  " + l).join("\n"));
    }
  }
}

if (query) {
  console.log(`\n── 検索「${query}」──`);
  const items = await searchItems(query);
  if (items.length === 0) console.log("  候補なし");
  for (const it of items.slice(0, 10)) show(it);
}

if (!asins.length && !query) {
  console.error("--asin / --search / --product のいずれかを指定してください");
  process.exit(1);
}
