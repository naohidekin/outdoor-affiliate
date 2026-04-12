#!/usr/bin/env node

/**
 * 商品画像URL修復スクリプト
 * imageUrl が未設定の商品に対して Amazon/楽天 URL から画像URLを推定・取得する
 *
 * 使い方:
 *   node scripts/fix-product-images.js --dry-run   # 対象リストのみ表示
 *   node scripts/fix-product-images.js --auto       # 取得した URL を products.json に書き戻し
 */

import fs from "fs";
import path from "path";
import { fileURLToPath } from "url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const PRODUCTS_PATH = path.join(__dirname, "..", "data", "products.json");

function extractAsin(amazonUrl) {
  if (!amazonUrl) return null;
  const match = amazonUrl.match(/\/dp\/([A-Z0-9]{10})/);
  return match ? match[1] : null;
}

function amazonImageUrl(asin) {
  // Amazon 商品画像（メイン画像、Lサイズ）
  return `https://m.media-amazon.com/images/P/${asin}.01._SCLZZZZZZZ_SX300_.jpg`;
}

async function fetchOgImage(url) {
  try {
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), 10000);

    const res = await fetch(url, {
      signal: controller.signal,
      headers: {
        "User-Agent":
          "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
      },
      redirect: "follow",
    });
    clearTimeout(timeout);

    if (!res.ok) return null;
    const html = await res.text();

    // og:image メタタグを探す
    const match = html.match(
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

function extractRakutenItemUrl(affiliateUrl) {
  if (!affiliateUrl) return null;
  // hb.afl.rakuten.co.jp のリダイレクトURLからpc=パラメータを取得
  const match = affiliateUrl.match(/[?&]pc=([^&]+)/);
  if (match) {
    try {
      return decodeURIComponent(match[1]);
    } catch {
      return null;
    }
  }
  // 直接楽天URLの場合
  if (affiliateUrl.includes("item.rakuten.co.jp")) {
    return affiliateUrl;
  }
  return null;
}

async function main() {
  const dryRun = process.argv.includes("--dry-run");
  const auto = process.argv.includes("--auto");

  if (!dryRun && !auto) {
    console.log("使い方:");
    console.log("  --dry-run  対象リストのみ表示");
    console.log("  --auto     画像URLを自動取得して products.json を更新");
    process.exit(0);
  }

  const products = JSON.parse(fs.readFileSync(PRODUCTS_PATH, "utf-8"));
  const missing = products.filter((p) => !p.imageUrl);

  console.log(`画像URL未設定: ${missing.length} / ${products.length} 商品\n`);

  if (dryRun) {
    for (const p of missing) {
      const asin = extractAsin(p.amazonUrl);
      const rakutenUrl = extractRakutenItemUrl(p.affiliateUrl);
      console.log(
        `  ${p.id} | ${p.brand || ""} ${p.name}` +
          `\n    ASIN: ${asin || "N/A"} | 楽天: ${rakutenUrl ? "あり" : "N/A"}`
      );
    }
    console.log(`\n--auto で画像URLを自動取得できます`);
    return;
  }

  // auto モード: 画像URL取得
  let updated = 0;
  let failed = 0;

  for (const p of missing) {
    let imageUrl = null;

    // 1. Amazon ASIN から画像URL生成
    const asin = extractAsin(p.amazonUrl);
    if (asin) {
      imageUrl = amazonImageUrl(asin);
    }

    // 2. Amazon画像がなければ楽天ページの og:image を試行
    if (!imageUrl) {
      const rakutenUrl = extractRakutenItemUrl(p.affiliateUrl);
      if (rakutenUrl) {
        console.log(`  [${p.id}] 楽天ページから og:image 取得中...`);
        imageUrl = await fetchOgImage(rakutenUrl);
      }
    }

    if (imageUrl) {
      // products.json 内の該当商品を更新
      const idx = products.findIndex((x) => x.id === p.id);
      if (idx >= 0) {
        products[idx].imageUrl = imageUrl;
        updated++;
        console.log(`  [${p.id}] ${imageUrl.slice(0, 80)}...`);
      }
    } else {
      failed++;
      console.log(`  [${p.id}] 画像URL取得失敗: ${p.brand} ${p.name}`);
    }
  }

  // 書き戻し
  fs.writeFileSync(PRODUCTS_PATH, JSON.stringify(products, null, 2) + "\n");
  console.log(`\n完了: ${updated}件更新 / ${failed}件失敗`);
}

main().catch((err) => {
  console.error("エラー:", err.message);
  process.exit(1);
});
