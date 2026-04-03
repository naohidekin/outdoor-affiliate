#!/usr/bin/env node

/**
 * Amazonリンク切れ自動チェック
 * products.jsonのamazonUrlを全件チェックし、404や無効なリンクを検出
 *
 * 使い方:
 *   node scripts/check-amazon-links.js
 *   node scripts/check-amazon-links.js --fix  (空URLの商品をレポート)
 */

import fs from "fs";
import path from "path";
import { fileURLToPath } from "url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const DATA_DIR = path.join(__dirname, "..", "data");

// .env.local を手動読み込み
const envPath = path.join(__dirname, "..", ".env.local");
if (fs.existsSync(envPath)) {
  const envContent = fs.readFileSync(envPath, "utf-8");
  for (const line of envContent.split("\n")) {
    const match = line.match(/^([^#=]+)=(.*)$/);
    if (match && !process.env[match[1].trim()]) {
      process.env[match[1].trim()] = match[2].trim();
    }
  }
}

const CONCURRENCY = 5;
const REQUEST_DELAY = 1000; // 1秒間隔（Amazon制限回避）

async function checkUrl(url) {
  try {
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), 15000);

    const res = await fetch(url, {
      method: "GET",
      signal: controller.signal,
      redirect: "follow",
      headers: {
        "User-Agent":
          "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        Accept: "text/html,application/xhtml+xml",
        "Accept-Language": "ja,en;q=0.9",
      },
    });

    clearTimeout(timeout);

    const text = await res.text();

    // Amazonの「ページが見つかりません」チェック
    const isNotFound =
      res.status === 404 ||
      text.includes("ページが見つかりません") ||
      text.includes("currently unavailable") ||
      text.includes("Page Not Found");

    // 「犬」ページ（Amazon 404相当）チェック
    const isDogPage =
      text.includes("SORRY") && text.includes("www.amazon.co.jp");

    return {
      status: res.status,
      ok: res.ok && !isNotFound && !isDogPage,
      redirected: res.redirected,
      finalUrl: res.url,
      notFound: isNotFound || isDogPage,
    };
  } catch (err) {
    return {
      status: 0,
      ok: false,
      error: err.message,
      notFound: false,
    };
  }
}

function sleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

async function main() {
  const products = JSON.parse(
    fs.readFileSync(path.join(DATA_DIR, "products.json"), "utf-8")
  );

  const withUrl = products.filter((p) => p.amazonUrl);
  const withoutUrl = products.filter((p) => !p.amazonUrl);

  console.log(`\n📦 商品数: ${products.length}`);
  console.log(`🔗 Amazon URL あり: ${withUrl.length}`);
  console.log(`❌ Amazon URL なし: ${withoutUrl.length}`);

  if (withoutUrl.length > 0) {
    console.log("\n--- URL未設定の商品 ---");
    withoutUrl.forEach((p) => console.log(`  ${p.id}: ${p.name}`));
  }

  console.log(`\n🔍 リンクチェック開始（${withUrl.length}件）...\n`);

  const broken = [];
  const errors = [];
  const ok = [];

  // バッチ処理（同時接続数制限）
  for (let i = 0; i < withUrl.length; i += CONCURRENCY) {
    const batch = withUrl.slice(i, i + CONCURRENCY);
    const results = await Promise.all(
      batch.map(async (product) => {
        const result = await checkUrl(product.amazonUrl);
        return { product, result };
      })
    );

    for (const { product, result } of results) {
      const short = product.amazonUrl.slice(0, 60);
      if (result.ok) {
        ok.push(product);
        process.stdout.write(`  ✅ ${product.id} ${product.name.slice(0, 25)}\n`);
      } else if (result.notFound) {
        broken.push({ product, result });
        process.stdout.write(
          `  🚨 ${product.id} ${product.name.slice(0, 25)} → 404/不存在\n`
        );
      } else if (result.error) {
        errors.push({ product, result });
        process.stdout.write(
          `  ⚠️ ${product.id} ${product.name.slice(0, 25)} → ${result.error.slice(0, 40)}\n`
        );
      } else {
        errors.push({ product, result });
        process.stdout.write(
          `  ⚠️ ${product.id} ${product.name.slice(0, 25)} → HTTP ${result.status}\n`
        );
      }
    }

    // レート制限回避
    if (i + CONCURRENCY < withUrl.length) {
      await sleep(REQUEST_DELAY);
    }
  }

  // レポート
  console.log("\n========== レポート ==========");
  console.log(`✅ 正常: ${ok.length}件`);
  console.log(`🚨 リンク切れ: ${broken.length}件`);
  console.log(`⚠️ エラー: ${errors.length}件`);

  if (broken.length > 0) {
    console.log("\n--- リンク切れ商品 ---");
    broken.forEach(({ product }) => {
      console.log(`  ${product.id}: ${product.name}`);
      console.log(`    URL: ${product.amazonUrl}`);
    });
  }

  if (errors.length > 0) {
    console.log("\n--- エラー商品 ---");
    errors.forEach(({ product, result }) => {
      console.log(`  ${product.id}: ${product.name}`);
      console.log(
        `    URL: ${product.amazonUrl}`
      );
      console.log(
        `    理由: ${result.error || `HTTP ${result.status}`}`
      );
    });
  }

  // 結果をJSONファイルに保存（他スクリプトから参照用）
  const report = {
    checkedAt: new Date().toISOString(),
    total: products.length,
    checked: withUrl.length,
    ok: ok.length,
    broken: broken.map(({ product }) => ({
      id: product.id,
      name: product.name,
      url: product.amazonUrl,
    })),
    errors: errors.map(({ product, result }) => ({
      id: product.id,
      name: product.name,
      url: product.amazonUrl,
      reason: result.error || `HTTP ${result.status}`,
    })),
    noUrl: withoutUrl.map((p) => ({ id: p.id, name: p.name })),
  };

  fs.writeFileSync(
    path.join(DATA_DIR, "link-check-report.json"),
    JSON.stringify(report, null, 2),
    "utf-8"
  );
  console.log("\n📄 レポート保存: data/link-check-report.json");
}

main().catch((err) => {
  console.error("エラー:", err.message);
  process.exit(1);
});
