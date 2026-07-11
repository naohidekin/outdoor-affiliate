#!/usr/bin/env node

/**
 * link-fix の自動候補が「なし/誤マッチ」だった商品だけ、人間が調整した
 * 検索キーワードで Creators API を再検索し、提案ファイルの候補を書き直す一回もの。
 *
 * 使い方:
 *   node scripts/refetch-candidates.mjs                 # 検索結果を表示するだけ
 *   node scripts/refetch-candidates.mjs --set knife-002=B0XXXXXXXX
 *       # そのASINをgetItemsで実在確認したうえで候補として書き込む（複数指定可）
 *   node scripts/refetch-candidates.mjs --auto          # 各商品の検索1位を候補として書き込む
 *
 * 書き込み後: git add data/link-fix-proposals.json → commit → push → 管理画面で承認
 */

import fs from "fs";
import path from "path";
import { fileURLToPath } from "url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const ROOT = path.join(__dirname, "..");

// .env.local 手動読み込み
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
if (!CREDENTIAL_ID || !CREDENTIAL_SECRET) {
  console.error("Creators API認証情報がありません（.env.local を確認）");
  process.exit(1);
}

// ─── 再検索ターゲット（キーワードは人間チューニング済み） ───
const TARGETS = [
  { id: "knife-002", keywords: "モーラナイフ ガーバーグ Garberg" },
  { id: "pillow-logos-camp-pillow", keywords: "ロゴス LOGOS キャンプ まくら ピロー" },
  { id: "dry-net-snowpeak", keywords: "スノーピーク ドライネット" },
  { id: "pillow-nemo-fillo-elite", keywords: "NEMO ニーモ フィロ ピロー 枕" },
  { id: "sierra-cup-bundok", keywords: "BUNDOK シェラカップ 600ml" },
];

// ─── Creators API（link-fix.mjs と同方式） ───
const TOKEN_ENDPOINTS = {
  "3.1": "https://api.amazon.com/auth/o2/token",
  "3.2": "https://api.amazon.co.uk/auth/o2/token",
  "3.3": "https://api.amazon.co.jp/auth/o2/token",
};
const API_BASE = "https://creatorsapi.amazon";
let cachedToken = null;

async function getAccessToken() {
  if (cachedToken && Date.now() < cachedToken.expiresAt) return cachedToken.token;
  const res = await fetch(TOKEN_ENDPOINTS[CREDENTIAL_VERSION] || TOKEN_ENDPOINTS["3.3"], {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      grant_type: "client_credentials",
      client_id: CREDENTIAL_ID,
      client_secret: CREDENTIAL_SECRET,
      scope: "creatorsapi::default",
    }),
  });
  if (!res.ok) throw new Error(`トークン取得失敗 ${res.status}`);
  const data = await res.json();
  cachedToken = { token: data.access_token, expiresAt: Date.now() + (Number(data.expires_in || 3600) - 60) * 1000 };
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
        "x-marketplace": "www.amazon.co.jp",
      },
      body: JSON.stringify(payload),
    });
    const text = await res.text();
    if (res.status === 429 && attempt < waits.length) {
      console.log(`  ⏳ レート制限 — ${waits[attempt] / 1000}秒待機`);
      await new Promise((r) => setTimeout(r, waits[attempt]));
      continue;
    }
    if (!res.ok) throw new Error(`Creators API ${res.status}: ${text.slice(0, 150)}`);
    return JSON.parse(text);
  }
}

const RESOURCES = ["itemInfo.title", "offersV2.listings.price"];

async function searchTop5(keywords) {
  const data = await creatorsApi("/catalog/v1/searchItems", {
    keywords,
    searchIndex: "All",
    itemCount: 5,
    partnerTag: PARTNER_TAG,
    resources: RESOURCES,
  });
  return data.searchResult?.items || [];
}

async function getItem(asin) {
  const data = await creatorsApi("/catalog/v1/getItems", {
    itemIds: [asin],
    partnerTag: PARTNER_TAG,
    resources: RESOURCES,
  });
  return (data.itemsResult?.items || [])[0] || null;
}

function fmt(it) {
  const title = it.itemInfo?.title?.displayValue || "(タイトル不明)";
  const price = it.offersV2?.listings?.[0]?.price?.money?.amount;
  return `${it.asin}  ${price ? "¥" + Number(price).toLocaleString() : "価格なし"}  ${title.slice(0, 70)}`;
}

function toCandidate(it) {
  return {
    asin: it.asin,
    title: it.itemInfo?.title?.displayValue || "",
    price: it.offersV2?.listings?.[0]?.price?.money?.amount ?? null,
    url: `https://www.amazon.co.jp/dp/${it.asin}?tag=${PARTNER_TAG}`,
  };
}

// ─── メイン ───
const AUTO = process.argv.includes("--auto");
const SETS = process.argv
  .filter((a) => a.startsWith("--set"))
  .flatMap(() => [])
  .concat(
    process.argv
      .map((a, i) => (a === "--set" ? process.argv[i + 1] : a.startsWith("--set=") ? a.slice(6) : null))
      .filter(Boolean)
  );

const proposalsPath = path.join(ROOT, "data", "link-fix-proposals.json");
const proposals = JSON.parse(fs.readFileSync(proposalsPath, "utf-8"));
const byId = new Map(proposals.quarantined.map((q) => [q.id, q]));

let wrote = false;

// --set id=ASIN 指定分: getItemsで実在確認して書き込み
for (const spec of SETS) {
  const [id, asin] = spec.split("=");
  const q = byId.get(id);
  if (!q) { console.log(`⏭️ 提案に無いID: ${id}`); continue; }
  const it = await getItem(asin);
  if (!it) { console.log(`❌ ${id}: ASIN ${asin} はAPIで見つかりません（適用中止）`); continue; }
  if (!it.offersV2?.listings?.length) console.log(`⚠️ ${id}: ${asin} はオファーなし（在庫切れの可能性）`);
  q.candidate = toCandidate(it);
  q.confidence = 90;
  wrote = true;
  console.log(`✅ ${id} ← ${fmt(it)}`);
  await new Promise((r) => setTimeout(r, 3000));
}

// 検索モード（--set が無いとき）
if (SETS.length === 0) {
  for (const t of TARGETS) {
    const q = byId.get(t.id);
    if (!q) { console.log(`⏭️ 提案に無いID: ${t.id}`); continue; }
    console.log(`\n■ ${t.id} — ${q.name}`);
    console.log(`  検索語: ${t.keywords}`);
    try {
      const items = await searchTop5(t.keywords);
      if (items.length === 0) console.log("  （ヒットなし）");
      items.forEach((it, i) => console.log(`  [${i + 1}] ${fmt(it)}`));
      if (AUTO && items.length > 0) {
        q.candidate = toCandidate(items[0]);
        q.confidence = 70;
        wrote = true;
        console.log(`  → [1] を候補として書き込み`);
      }
    } catch (err) {
      console.log(`  ❌ 検索失敗: ${err.message}`);
    }
    await new Promise((r) => setTimeout(r, 3000));
  }
}

if (wrote) {
  proposals.generatedAt = new Date().toISOString();
  fs.writeFileSync(proposalsPath, JSON.stringify(proposals, null, 2) + "\n", "utf-8");
  console.log(`\n📝 ${proposalsPath} を更新しました。`);
  console.log("次: git add data/link-fix-proposals.json && git commit -m 'data: 差し替え候補を手動再検索で補充' && git push");
} else if (SETS.length === 0 && !AUTO) {
  console.log("\n（表示のみ。候補を書き込むには --auto か --set id=ASIN を付けて再実行）");
}
