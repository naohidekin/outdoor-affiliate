#!/usr/bin/env node

/**
 * fix-blank-amazon-images.mjs — Amazon P/形式画像の「空白画像」検出・修復
 *
 * 背景: m.media-amazon.com/images/P/{ASIN} 形式の画像URLは、ASINに画像が
 * 登録されていない場合でも HTTP 200 で 1x1 の空白GIF（約40バイト）を返す。
 * このためステータスチェックでは検出できず、サイト上では「画像が表示されない」
 * 状態になる（◯選記事のタイルヒーローに穴が開く実害が出た）。
 *
 * 修復の優先順位（楽天への直接スクレイプ連発はブロックされるためAPI優先）:
 *   1. 楽天Ichiba API itemCode直引き（affiliateUrlの商品URLから shop:code を抽出）
 *   2. 楽天Ichiba API キーワード検索（商品名・先頭1件 → ログに「要確認」表示）
 *   3. 商品ページの og:image（API不可時のフォールバック）
 * いずれも差し替え前に実画像として取得検証する。
 *
 * 使い方:
 *   node scripts/fix-blank-amazon-images.mjs --dry-run   # 検出のみ
 *   node scripts/fix-blank-amazon-images.mjs             # 修復して書き込み
 */

import fs from "fs";
import path from "path";
import { fileURLToPath } from "url";
import { loadEnv } from "../src/lib/x-agent-utils.mjs";

loadEnv();

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const PRODUCTS_PATH = path.join(__dirname, "..", "data", "products.json");
const dryRun = process.argv.includes("--dry-run");

const RAKUTEN_API_URL =
  "https://openapi.rakuten.co.jp/ichibams/api/IchibaItem/Search/20220601";
const APP_ID = process.env.RAKUTEN_APP_ID;
const ACCESS_KEY = process.env.RAKUTEN_ACCESS_KEY;
const AFFILIATE_ID =
  process.env.RAKUTEN_AFFILIATE_ID || "18eb3228.621d8df3.18eb3229.ec5f8d49";

const UA =
  "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36";
const MIN_IMAGE_BYTES = 2048; // 空白GIFは約40B、実画像は数KB以上
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

async function fetchBytes(url) {
  try {
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), 10000);
    const res = await fetch(url, {
      signal: controller.signal,
      headers: { "User-Agent": UA, Referer: "https://camp-gear-lab.com/" },
      redirect: "follow",
    });
    clearTimeout(timeout);
    if (!res.ok) return { ok: false, status: res.status };
    const ct = res.headers.get("content-type") || "";
    const buf = await res.arrayBuffer();
    return {
      ok: ct.startsWith("image") && buf.byteLength >= MIN_IMAGE_BYTES,
      status: res.status,
      bytes: buf.byteLength,
      contentType: ct,
    };
  } catch (e) {
    return { ok: false, status: "ERR:" + e.message.slice(0, 30) };
  }
}

function extractRakutenItemUrl(affiliateUrl) {
  if (!affiliateUrl) return null;
  const match = affiliateUrl.match(/[?&]pc=([^&]+)/);
  if (match) {
    try {
      const url = decodeURIComponent(match[1]);
      return url.includes("item.rakuten.co.jp") ? url : null;
    } catch {
      return null;
    }
  }
  return affiliateUrl.includes("item.rakuten.co.jp") ? affiliateUrl : null;
}

function parseItemCode(itemUrl) {
  const m = itemUrl.match(/item\.rakuten\.co\.jp\/([^/]+)\/([^/?#]+)/);
  return m ? `${m[1]}:${m[2]}` : null;
}

async function rakutenApi(extraParams) {
  if (!APP_ID || !ACCESS_KEY) return null;
  const params = new URLSearchParams({
    applicationId: APP_ID,
    accessKey: ACCESS_KEY,
    affiliateId: AFFILIATE_ID,
    hits: "1",
    imageFlag: "1",
    formatVersion: "2",
    ...extraParams,
  });
  try {
    const res = await fetch(`${RAKUTEN_API_URL}?${params}`, {
      headers: {
        Origin: "https://camp-gear-lab.com",
        Referer: "https://camp-gear-lab.com/",
      },
    });
    if (!res.ok) return null;
    const data = await res.json();
    const item = (data.Items || [])[0];
    if (!item) return null;
    const img = (item.mediumImageUrls && item.mediumImageUrls[0]) || "";
    return img || null;
  } catch {
    return null;
  }
}

async function fetchOgImage(url) {
  try {
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), 10000);
    const res = await fetch(url, {
      signal: controller.signal,
      headers: { "User-Agent": UA },
      redirect: "follow",
    });
    clearTimeout(timeout);
    if (!res.ok) return null;
    const html = await res.text();
    const match =
      html.match(
        /<meta\s+(?:property|name)=["']og:image["']\s+content=["']([^"']+)["']/i
      ) ||
      html.match(
        /content=["']([^"']+)["']\s+(?:property|name)=["']og:image["']/i
      );
    return match ? match[1] : null;
  } catch {
    return null;
  }
}

function upsize(url) {
  return url.replace(/_ex=\d+x\d+/, "_ex=600x600");
}

const products = JSON.parse(fs.readFileSync(PRODUCTS_PATH, "utf8"));
const now = new Date().toISOString();
const targets = products.filter((p) =>
  (p.imageUrl || "").includes("m.media-amazon.com/images/P/")
);
console.log(`Amazon P/形式の画像: ${targets.length}件を検査します`);
console.log(
  `楽天API: ${APP_ID && ACCESS_KEY ? "利用可能" : "キー未設定（og:imageのみで修復試行）"}\n`
);

let blank = 0;
let fixed = 0;
const unresolved = [];

for (const p of targets) {
  const check = await fetchBytes(p.imageUrl);
  if (check.ok) continue;
  blank++;
  console.log(
    `空白/取得不能: ${p.id} | ${p.name.slice(0, 32)} (${check.bytes ?? ""}B ${check.status})`
  );

  const itemUrl = extractRakutenItemUrl(p.affiliateUrl);
  let candidate = null;
  let via = "";

  // 1) 楽天API itemCode 直引き
  if (itemUrl) {
    const itemCode = parseItemCode(itemUrl);
    if (itemCode) {
      candidate = await rakutenApi({ itemCode });
      via = "API:itemCode";
      await sleep(1100); // 楽天APIは1req/秒制限
    }
  }
  // 2) 楽天API キーワード検索（商品名）
  if (!candidate) {
    candidate = await rakutenApi({ keyword: p.name.slice(0, 60) });
    via = "API:keyword(要確認)";
    await sleep(1100);
  }
  // 3) og:image フォールバック
  if (!candidate && itemUrl) {
    candidate = await fetchOgImage(itemUrl);
    via = "og:image";
    await sleep(1100);
  }

  if (!candidate) {
    unresolved.push(`${p.id} | ${p.name.slice(0, 32)}`);
    continue;
  }
  candidate = upsize(candidate);
  const verify = await fetchBytes(candidate);
  if (!verify.ok) {
    unresolved.push(`${p.id} | ${p.name.slice(0, 32)} (検証失敗: ${candidate.slice(0, 50)})`);
    continue;
  }
  console.log(`  → 差し替え[${via}]: ${candidate.slice(0, 72)}`);
  if (!dryRun) {
    p.imageUrl = candidate;
    p.updatedAt = now;
  }
  fixed++;
}

if (!dryRun && fixed > 0) {
  fs.writeFileSync(PRODUCTS_PATH, JSON.stringify(products, null, 2) + "\n");
}
console.log(
  `\n${dryRun ? "[DRY RUN] " : ""}検査${targets.length}件 / 空白${blank}件 / 修復${fixed}件 / 未解決${unresolved.length}件`
);
if (unresolved.length) {
  console.log("未解決（手動対応が必要）:");
  unresolved.forEach((u) => console.log("  -", u));
}
if (!dryRun && fixed > 0) {
  console.log("→ 反映には node scripts/sync-to-supabase.js の実行が必要です");
}
