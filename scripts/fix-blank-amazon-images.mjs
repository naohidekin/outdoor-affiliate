#!/usr/bin/env node

/**
 * fix-blank-amazon-images.mjs — Amazon P/形式画像の「空白画像」検出・修復
 *
 * 背景: m.media-amazon.com/images/P/{ASIN} 形式の画像URLは、ASINに画像が
 * 登録されていない場合でも HTTP 200 で 1x1 の空白GIF（約40バイト）を返す。
 * このためステータスチェックでは検出できず、サイト上では「画像が表示されない」
 * 状態になる（◯選記事のタイルヒーローに穴が開く実害が出た）。
 *
 * 処理:
 * 1. imageUrl が m.media-amazon の全商品について画像を実取得し、
 *    Content-Type が image でない or 2KB未満 のものを「空白」と判定
 * 2. 空白だった商品は、affiliateUrl から楽天商品ページURLを取り出し、
 *    og:image を取得して差し替え（item.rakuten.co.jp のページに限る）
 * 3. og:image も実取得して画像であることを検証してから書き込む
 * 4. 変更した商品は updatedAt を更新（syncで確実に反映させるため）
 *
 * 使い方:
 *   node scripts/fix-blank-amazon-images.mjs --dry-run   # 検出のみ
 *   node scripts/fix-blank-amazon-images.mjs             # 修復して書き込み
 */

import fs from "fs";
import path from "path";
import { fileURLToPath } from "url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const PRODUCTS_PATH = path.join(__dirname, "..", "data", "products.json");
const dryRun = process.argv.includes("--dry-run");

const UA =
  "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36";
const MIN_IMAGE_BYTES = 2048; // 空白GIFは約40B、実画像は数KB以上

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

const products = JSON.parse(fs.readFileSync(PRODUCTS_PATH, "utf8"));
const now = new Date().toISOString();
const targets = products.filter((p) =>
  (p.imageUrl || "").includes("m.media-amazon.com/images/P/")
);
console.log(`Amazon P/形式の画像: ${targets.length}件を検査します\n`);

let blank = 0;
let fixed = 0;
let unresolved = [];

for (const p of targets) {
  const check = await fetchBytes(p.imageUrl);
  if (check.ok) continue;
  blank++;
  console.log(
    `空白/取得不能: ${p.id} | ${p.name.slice(0, 30)} (${check.bytes ?? ""}B ${check.status})`
  );

  // 楽天商品ページの og:image から代替画像を取得
  const itemUrl = extractRakutenItemUrl(p.affiliateUrl);
  if (!itemUrl) {
    unresolved.push(p.id + " (楽天商品URLなし)");
    continue;
  }
  const og = await fetchOgImage(itemUrl);
  if (!og) {
    unresolved.push(p.id + " (og:image取得失敗)");
    continue;
  }
  // 楽天サムネ形式ならサイズを上げる
  const candidate = og.replace(/_ex=\d+x\d+/, "_ex=600x600");
  const verify = await fetchBytes(candidate);
  if (!verify.ok) {
    unresolved.push(p.id + " (og:image検証失敗: " + candidate.slice(0, 50) + ")");
    continue;
  }
  console.log(`  → 差し替え: ${candidate.slice(0, 70)}`);
  if (!dryRun) {
    p.imageUrl = candidate;
    p.updatedAt = now;
  }
  fixed++;
  await new Promise((r) => setTimeout(r, 300)); // 楽天への連続アクセスを抑制
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
