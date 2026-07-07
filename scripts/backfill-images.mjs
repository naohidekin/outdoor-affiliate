#!/usr/bin/env node

/**
 * Backfill Product Images — Amazon PA-API から本物の商品画像URLを取得
 *
 * ASINから /images/P/ を組み立てる方式は画像が存在しないASINで失敗するため、
 * PA-API GetItems（Images.Primary.Large）で確実な画像URL（/images/I/…）を取得し
 * products.json の imageUrl を更新する。
 *
 * 必要env（.env.local）:
 *   AMAZON_ACCESS_KEY / AMAZON_SECRET_KEY / AMAZON_PARTNER_TAG(任意)
 *
 * 使い方:
 *   node scripts/backfill-images.mjs --dry-run          # 取得結果の表示のみ
 *   node scripts/backfill-images.mjs                    # 既定の対象IDを更新
 *   node scripts/backfill-images.mjs id1 id2 ...        # 対象IDを指定
 */

import fs from "fs";
import path from "path";
import crypto from "crypto";
import { fileURLToPath } from "url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const ROOT = path.join(__dirname, "..");

// .env.local を読み込む（AMAZON_ACCESS_KEY 等）
function loadEnv() {
  const envPath = path.join(ROOT, ".env.local");
  if (!fs.existsSync(envPath)) return;
  for (const line of fs.readFileSync(envPath, "utf-8").split("\n")) {
    const m = line.match(/^([^#=]+)=(.*)$/);
    if (m) process.env[m[1].trim()] = m[2].trim().replace(/^["']|["']$/g, "");
  }
}
loadEnv();

const ACCESS_KEY = process.env.AMAZON_ACCESS_KEY;
const SECRET_KEY = process.env.AMAZON_SECRET_KEY;
const PARTNER_TAG = process.env.AMAZON_PARTNER_TAG || "camp78-22";
const HOST = "webservices.amazon.co.jp";
const REGION = "us-west-2";
const SERVICE = "ProductAdvertisingAPI";

const DRY_RUN = process.argv.includes("--dry-run");
const argIds = process.argv.slice(2).filter((a) => !a.startsWith("--"));

// 既定の対象（今回 /images/P/ で失敗した13商品）
const DEFAULT_IDS = [
  "neck-thanko-lite", "neck-sony-reonpocket5", "neck-suo-ring",
  "neck-suo-ring-plus", "neck-mizuno-cooling-towel", "cooler-ecoflow-wave3",
  "cot-helinox-cot-one", "cot-waq-2way", "cot-naturehike-greenfield",
  "mat-coleman-highpeak", "mat-waq-8cm", "mat-waq-10cm", "mat-thermarest-prolite",
];

// --- PA-API v5 AWS Signature V4（price-monitor.js と同一） ---
function hmacSha256(key, data) { return crypto.createHmac("sha256", key).update(data).digest(); }
function sha256(data) { return crypto.createHash("sha256").update(data).digest("hex"); }
function getSignatureKey(key, dateStamp, region, service) {
  const kDate = hmacSha256("AWS4" + key, dateStamp);
  const kRegion = hmacSha256(kDate, region);
  const kService = hmacSha256(kRegion, service);
  return hmacSha256(kService, "aws4_request");
}

async function paApiRequest(operation, payload) {
  const now = new Date();
  const amzDate = now.toISOString().replace(/[-:]/g, "").replace(/\.\d+Z$/, "Z");
  const dateStamp = amzDate.slice(0, 8);
  const body = JSON.stringify(payload);
  const headers = {
    "content-encoding": "amz-1.0",
    "content-type": "application/json; charset=utf-8",
    host: HOST,
    "x-amz-date": amzDate,
    "x-amz-target": `com.amazon.paapi5.v1.ProductAdvertisingAPIv1.${operation}`,
  };
  const signedHeaders = Object.keys(headers).sort().join(";");
  const canonicalHeaders = Object.keys(headers).sort().map((k) => `${k}:${headers[k]}`).join("\n");
  const apiPath = `/paapi5/${operation === "GetItems" ? "getitems" : operation.toLowerCase()}`;
  const canonicalRequest = ["POST", apiPath, "", canonicalHeaders + "\n", signedHeaders, sha256(body)].join("\n");
  const credentialScope = `${dateStamp}/${REGION}/${SERVICE}/aws4_request`;
  const stringToSign = ["AWS4-HMAC-SHA256", amzDate, credentialScope, sha256(canonicalRequest)].join("\n");
  const signingKey = getSignatureKey(SECRET_KEY, dateStamp, REGION, SERVICE);
  const signature = hmacSha256(signingKey, stringToSign).toString("hex");
  const authHeader = `AWS4-HMAC-SHA256 Credential=${ACCESS_KEY}/${credentialScope}, SignedHeaders=${signedHeaders}, Signature=${signature}`;
  const res = await fetch(`https://${HOST}${apiPath}`, {
    method: "POST",
    headers: { ...headers, Authorization: authHeader },
    body,
  });
  if (!res.ok) {
    const text = await res.text();
    throw new Error(`PA-API error ${res.status}: ${text.slice(0, 300)}`);
  }
  return res.json();
}

function extractAsin(url) {
  const m = (url || "").match(/\/dp\/([A-Z0-9]{10})/);
  return m ? m[1] : null;
}

async function getImages(asins) {
  const payload = {
    ItemIds: asins,
    Resources: ["Images.Primary.Large", "ItemInfo.Title"],
    PartnerTag: PARTNER_TAG,
    PartnerType: "Associates",
    Marketplace: "www.amazon.co.jp",
  };
  const data = await paApiRequest("GetItems", payload);
  return data.ItemsResult?.Items || [];
}

async function main() {
  if (!ACCESS_KEY || !SECRET_KEY) {
    console.error("⚠️ AMAZON_ACCESS_KEY / AMAZON_SECRET_KEY が未設定です（.env.local）。中止。");
    process.exit(1);
  }

  const productsPath = path.join(ROOT, "data", "products.json");
  const products = JSON.parse(fs.readFileSync(productsPath, "utf-8"));
  const byId = Object.fromEntries(products.map((p) => [p.id, p]));

  const ids = (argIds.length ? argIds : DEFAULT_IDS).filter((id) => byId[id]);

  // ASIN を集める（amazonUrl の /dp/ から）
  const targets = [];
  const skipped = [];
  for (const id of ids) {
    const p = byId[id];
    const asin = extractAsin(p.amazonUrl);
    if (asin) targets.push({ id, asin, p });
    else skipped.push(id);
  }
  if (skipped.length) console.log(`⏭️  ASIN無しでスキップ: ${skipped.join(", ")}`);

  const asin2id = Object.fromEntries(targets.map((t) => [t.asin, t.id]));
  let updated = 0, failed = 0;

  // 10件ずつ
  for (let i = 0; i < targets.length; i += 10) {
    const batch = targets.slice(i, i + 10).map((t) => t.asin);
    let items = [];
    try {
      items = await getImages(batch);
    } catch (err) {
      console.error(`❌ バッチ取得失敗 (${batch.join(",")}): ${err.message}`);
      failed += batch.length;
      continue;
    }
    const gotAsins = new Set();
    for (const item of items) {
      const asin = item.ASIN;
      const url = item.Images?.Primary?.Large?.URL;
      const id = asin2id[asin];
      if (!id) continue;
      gotAsins.add(asin);
      if (!url) { console.log(`⚠️  画像なし: ${id} (${asin})`); failed++; continue; }
      console.log(`✅ ${id}: ${url}`);
      if (!DRY_RUN) { byId[id].imageUrl = url; byId[id].updatedAt = new Date().toISOString(); }
      updated++;
    }
    // 返って来なかったASIN
    for (const asin of batch) {
      if (!gotAsins.has(asin)) { console.log(`⚠️  PA-API未返却: ${asin2id[asin]} (${asin})`); failed++; }
    }
  }

  if (!DRY_RUN && updated > 0) {
    fs.writeFileSync(productsPath, JSON.stringify(products, null, 2) + "\n", "utf-8");
    console.log(`\n📝 products.json を更新（${updated}件）`);
  } else {
    console.log(`\n(DRY RUN or 更新なし) 成功:${updated} 失敗:${failed}`);
  }
  console.log(`完了: 成功 ${updated} / 失敗 ${failed} / スキップ ${skipped.length}`);
}

main().catch((e) => { console.error(e); process.exit(1); });
