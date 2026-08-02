#!/usr/bin/env node
/**
 * 重複登録された商品の現在価格を楽天APIで確認する（読み取り専用）
 *
 * 背景（2026-08-01 データ監査）: 同一商品が2つのIDで登録されており、
 * 記事によって違う価格が表示されている（例: スノーピーク焚火台Lが
 * ¥25,300 と ¥18,600 で並存）。統合前に「どちらが実勢か」を確定させる。
 *
 * products.json は一切変更しない。結果を見て統合先を決めるための下調べ。
 *
 * 使い方（自宅Wi-Fiから。アクセスキーのIP許可リストが必要）:
 *   node scripts/check-duplicate-prices.mjs
 */
import fs from "node:fs";
import { loadEnv } from "../src/lib/x-agent-utils.mjs";

loadEnv();

const RAKUTEN_API_URL =
  "https://openapi.rakuten.co.jp/ichibams/api/IchibaItem/Search/20220601";
const AFFILIATE_ID =
  process.env.RAKUTEN_AFFILIATE_ID || "18eb3228.621d8df3.18eb3229.ec5f8d49";
const appId = process.env.RAKUTEN_APP_ID;
const accessKey = process.env.RAKUTEN_ACCESS_KEY;
if (!appId || !accessKey) {
  console.error("RAKUTEN_APP_ID / RAKUTEN_ACCESS_KEY が未設定です");
  process.exit(1);
}

// 監査で検出した重複5組（両方が公開記事で使われているもの）
const DUP_GROUPS = [
  ["fp-003", "fp-006"], // スノーピーク 焚火台L（¥25,300 / ¥18,600）
  ["sb-kids-003", "sb-budget-002"], // ロゴス スランバーシュラフ・2
  ["tent-solo-003", "tent-001"], // コールマン ツーリングドームST
  ["tent-sp-amenity-dome-m", "tent-002"], // スノーピーク アメニティドームM
  ["firepit-picogrill-398", "fp-001"], // ピコグリル398
];

const products = JSON.parse(fs.readFileSync("data/products.json", "utf8"));
const byId = new Map(products.map((p) => [p.id, p]));
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

const USED_SHOP = /2nd STREET|セカンドストリート|ワットマン|リサイクル|中古|質屋/i;

function sanitize(s) {
  return s
    .replace(/[×/＋+|｜]/g, " ")
    .split(/\s+/)
    .filter((t) => [...t].length >= 2)
    .join(" ")
    .slice(0, 120);
}

async function search(keyword) {
  const params = new URLSearchParams({
    applicationId: appId,
    accessKey,
    affiliateId: AFFILIATE_ID,
    keyword: sanitize(keyword),
    hits: "20",
    sort: "+itemPrice", // 安い順。相場の下限を掴む
    format: "json",
    formatVersion: "2",
  });
  const res = await fetch(`${RAKUTEN_API_URL}?${params}`, {
    headers: { Origin: "https://camp-gear-lab.com", Referer: "https://camp-gear-lab.com/" },
  });
  if (!res.ok) {
    const body = await res.text().catch(() => "");
    if (body.includes("CLIENT_IP_NOT_ALLOWED")) {
      console.error(
        "\nアクセスキーがIP制限で拒否されました。\n" +
          "https://webservice.rakuten.co.jp/ で現在のIP（curl -s ifconfig.me）を許可リストに追加してください。"
      );
      process.exit(1);
    }
    console.warn(`  API ${res.status}: ${body.slice(0, 120)}`);
    return [];
  }
  const data = await res.json();
  return (data.Items || []).filter((i) => !USED_SHOP.test(i.shopName || ""));
}

console.log("\n=== 重複商品の現在価格を確認（products.jsonは変更しません）===\n");

for (const ids of DUP_GROUPS) {
  const list = ids.map((id) => byId.get(id)).filter(Boolean);
  if (list.length < 2) continue;
  const name = list[0].name;
  await sleep(1500);
  const items = await search(name);
  const prices = items.map((i) => i.itemPrice).filter((v) => v > 0);

  console.log(`■ ${name}`);
  for (const p of list) {
    console.log(`   登録: ${p.id.padEnd(26)} ¥${(p.price || 0).toLocaleString()}`);
  }
  if (prices.length === 0) {
    console.log("   楽天: 該当なし（型番違い・廃番の可能性）\n");
    continue;
  }
  // 中央値を実勢の目安にする（最安は転売・訳あり品が混じるため）
  const sorted = [...prices].sort((a, b) => a - b);
  const median = sorted[Math.floor(sorted.length / 2)];
  console.log(
    `   楽天: ${prices.length}件 最安¥${sorted[0].toLocaleString()} 中央値¥${median.toLocaleString()} 最高¥${sorted[sorted.length - 1].toLocaleString()}`
  );
  const best = list.reduce((a, b) =>
    Math.abs((a.price || 0) - median) <= Math.abs((b.price || 0) - median) ? a : b
  );
  console.log(`   → 実勢に近いのは ${best.id}（¥${(best.price || 0).toLocaleString()}）`);
  console.log(`   参考: ${items[Math.floor(items.length / 2)]?.itemName?.slice(0, 50) || ""}\n`);
}

console.log("この結果を見て、統合先（残すID）と正しい価格を決めてください。");
