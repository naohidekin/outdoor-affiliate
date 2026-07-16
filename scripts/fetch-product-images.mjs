#!/usr/bin/env node
// 商品画像URLをAmazon Creators APIから取得してproducts.jsonに書き込む。
// リモート開発環境からはAmazon/楽天の画像URLを検証できないため、
// 実際の画像取得はMac上でこのスクリプトを実行して行う（link-fix.mjsと同じ認証）。
//
// 使い方:
//   npm run images:fetch                → imageUrl空 & amazonUrlあり の全商品を対象
//   npm run images:fetch -- id1 id2    → 指定した商品IDのみ対象
//   npm run images:fetch -- --dry-run  → 書き込まずに結果表示
//   npm run images:fetch -- --price    → 価格もofferの現在値で更新する

import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const ROOT = path.join(path.dirname(fileURLToPath(import.meta.url)), "..");

// .env.local 手動読み込み（link-fix.mjs と同方式）
const envPath = path.join(ROOT, ".env.local");
if (fs.existsSync(envPath)) {
  for (const line of fs.readFileSync(envPath, "utf-8").split("\n")) {
    const m = line.match(/^([^#=]+)=(.*)$/);
    if (m && !process.env[m[1].trim()]) process.env[m[1].trim()] = m[2].trim();
  }
}

const CREDENTIAL_ID = process.env.AMAZON_CREDENTIAL_ID || process.env.AMAZON_ACCESS_KEY;
const CREDENTIAL_SECRET = process.env.AMAZON_CREDENTIAL_SECRET || process.env.AMAZON_SECRET_KEY;
const CREDENTIAL_VERSION = process.env.AMAZON_CREDENTIAL_VERSION || "3.3";
const PARTNER_TAG = process.env.AMAZON_PARTNER_TAG || "camp78-22";

const TOKEN_ENDPOINTS = {
  "3.1": "https://api.amazon.com/auth/o2/token",
  "3.2": "https://api.amazon.co.uk/auth/o2/token",
  "3.3": "https://api.amazon.co.jp/auth/o2/token",
};
const API_BASE = "https://creatorsapi.amazon";
const MARKETPLACE = "www.amazon.co.jp";

const args = process.argv.slice(2);
const DRY_RUN = args.includes("--dry-run");
const UPDATE_PRICE = args.includes("--price");
const targetIds = args.filter((a) => !a.startsWith("--"));

if (!CREDENTIAL_ID || !CREDENTIAL_SECRET) {
  console.error("❌ Creators API認証情報がありません（.env.local の AMAZON_CREDENTIAL_ID / AMAZON_CREDENTIAL_SECRET）");
  process.exit(1);
}

let cachedToken = null;
async function getAccessToken() {
  if (cachedToken && Date.now() < cachedToken.expiresAt) return cachedToken.token;
  const endpoint = TOKEN_ENDPOINTS[CREDENTIAL_VERSION] || TOKEN_ENDPOINTS["3.3"];
  const res = await fetch(endpoint, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      grant_type: "client_credentials",
      client_id: CREDENTIAL_ID,
      client_secret: CREDENTIAL_SECRET,
      scope: "creatorsapi::default",
    }),
  });
  if (!res.ok) throw new Error(`トークン取得失敗 ${res.status}: ${(await res.text()).slice(0, 200)}`);
  const data = await res.json();
  cachedToken = {
    token: data.access_token,
    expiresAt: Date.now() + (Number(data.expires_in || 3600) - 60) * 1000,
  };
  return cachedToken.token;
}

async function creatorsApi(apiPath, payload) {
  const waits = [3000, 8000, 20000];
  for (let attempt = 0; ; attempt++) {
    const token = await getAccessToken();
    const res = await fetch(`${API_BASE}${apiPath}`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        Authorization: `Bearer ${token}`,
        "x-marketplace": MARKETPLACE,
      },
      body: JSON.stringify(payload),
    });
    const text = await res.text();
    if (res.status === 429 && attempt < waits.length) {
      const wait = waits[attempt];
      console.log(`  ⏳ レート制限(429) — ${wait / 1000}秒待って再試行 (${attempt + 1}/${waits.length})`);
      await new Promise((r) => setTimeout(r, wait));
      continue;
    }
    if (!res.ok) throw new Error(`Creators API ${res.status}: ${text.slice(0, 300)}`);
    return JSON.parse(text);
  }
}

function asinOf(url) {
  const m = (url || "").match(/\/dp\/([A-Z0-9]{10})/);
  return m ? m[1] : null;
}

function imageUrlOf(item) {
  const p = item.images?.primary;
  return p?.large?.url || p?.medium?.url || p?.small?.url || null;
}

const productsPath = path.join(ROOT, "data", "products.json");
const products = JSON.parse(fs.readFileSync(productsPath, "utf-8"));

const targets = products.filter((p) => {
  if (targetIds.length) return targetIds.includes(p.id);
  return !p.imageUrl && asinOf(p.amazonUrl);
});

if (!targets.length) {
  console.log("対象商品なし（imageUrl空 & amazonUrlあり の商品がありません）");
  process.exit(0);
}

console.log(`[images:fetch] 対象 ${targets.length} 件${DRY_RUN ? "（dry-run）" : ""}`);
const byAsin = new Map();
for (const p of targets) {
  const asin = asinOf(p.amazonUrl);
  if (!asin) {
    console.log(`  ⚠️ ${p.id}: amazonUrlからASINが取れないためスキップ`);
    continue;
  }
  byAsin.set(asin, p);
}

const asins = [...byAsin.keys()];
let updated = 0;
for (let i = 0; i < asins.length; i += 10) {
  const batch = asins.slice(i, i + 10);
  const data = await creatorsApi("/catalog/v1/getItems", {
    itemIds: batch,
    partnerTag: PARTNER_TAG,
    resources: ["itemInfo.title", "images.primary.large", "offersV2.listings.price"],
  });
  for (const item of data.itemsResult?.items || []) {
    const p = byAsin.get(item.asin);
    if (!p) continue;
    const img = imageUrlOf(item);
    const title = item.itemInfo?.title?.displayValue || "";
    if (img) {
      console.log(`  ✅ ${p.id}: ${img}`);
      console.log(`     （${title.slice(0, 60)}）`);
      if (!DRY_RUN) {
        p.imageUrl = img;
        p.updatedAt = new Date().toISOString();
        updated++;
      }
    } else {
      console.log(`  ⚠️ ${p.id}: APIレスポンスに画像なし`);
    }
    const amount = item.offersV2?.listings?.[0]?.price?.money?.amount;
    if (UPDATE_PRICE && amount && !DRY_RUN) {
      console.log(`     価格更新: ¥${p.price} → ¥${Math.round(amount)}`);
      p.price = Math.round(amount);
    }
  }
  for (const e of data.errors || []) {
    console.log(`  ⚠️ APIエラー: ${e.code} ${String(e.message).slice(0, 100)}`);
  }
  if (i + 10 < asins.length) await new Promise((r) => setTimeout(r, 3000));
}

if (!DRY_RUN && updated) {
  fs.writeFileSync(productsPath, JSON.stringify(products, null, 2) + "\n");
  console.log(`\n✅ products.json に ${updated} 件書き込みました。反映は npm run db:sync を実行してください。`);
} else if (DRY_RUN) {
  console.log("\n（dry-runのため書き込みなし）");
}
