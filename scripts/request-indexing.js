#!/usr/bin/env node

/**
 * Google Indexing API — URL一括インデックスリクエスト
 *
 * 使い方:
 *   node scripts/request-indexing.js                # サイトマップ全URLをリクエスト
 *   node scripts/request-indexing.js --dry-run      # 確認のみ
 *   node scripts/request-indexing.js --urls url1 url2  # 指定URLのみ
 */

import { google } from "googleapis";
import { loadEnv } from "../src/lib/x-agent-utils.mjs";

loadEnv();

const credentials = JSON.parse(process.env.INDEXING_CREDENTIALS || "{}");
const dryRun = process.argv.includes("--dry-run");

// ─── 対象URL ─────────────────────────────────────────

function getUrls() {
  const urlsIdx = process.argv.indexOf("--urls");
  if (urlsIdx !== -1) {
    return process.argv.slice(urlsIdx + 1).filter(u => u.startsWith("http"));
  }

  // デフォルト: GSCで「検出 - インデックス未登録」の全URL
  return [
    "https://camp-gear-lab.com/articles/budget-sleeping-bag-ranking",
    "https://camp-gear-lab.com/articles/camp-chair-ranking",
    "https://camp-gear-lab.com/articles/camp-table-ranking",
    "https://camp-gear-lab.com/articles/camping-beginner-gear-checklist",
    "https://camp-gear-lab.com/articles/cooler-box-ranking",
    "https://camp-gear-lab.com/articles/duo-tent-ranking",
    "https://camp-gear-lab.com/articles/firepit-3way-showdown",
    "https://camp-gear-lab.com/articles/firepit-solo-ranking",
    "https://camp-gear-lab.com/articles/rainwear-ranking",
    "https://camp-gear-lab.com/articles/solo-tent-ranking",
    "https://camp-gear-lab.com/articles/tarp-ranking",
    "https://camp-gear-lab.com/category/backpack",
    "https://camp-gear-lab.com/category/burner",
    "https://camp-gear-lab.com/category/chair",
    "https://camp-gear-lab.com/category/cooler",
    "https://camp-gear-lab.com/category/firepit",
    "https://camp-gear-lab.com/category/light",
    "https://camp-gear-lab.com/category/shoes",
    "https://camp-gear-lab.com/category/sleeping-bag",
    "https://camp-gear-lab.com/category/table",
    "https://camp-gear-lab.com/category/tarp",
    "https://camp-gear-lab.com/category/tent",
    "https://camp-gear-lab.com/category/wear",
  ];
}

// ─── メイン ─────────────────────────────────────────

async function main() {
  const urls = getUrls();
  console.log(`\n=== Indexing API リクエスト ${dryRun ? "(DRY RUN)" : ""} ===`);
  console.log(`対象: ${urls.length}件\n`);

  if (dryRun) {
    urls.forEach(u => console.log(`  [DRY] ${u}`));
    return;
  }

  const auth = new google.auth.GoogleAuth({
    credentials,
    scopes: ["https://www.googleapis.com/auth/indexing"],
  });

  const indexing = google.indexing({ version: "v3", auth });

  let success = 0;
  let failed = 0;

  for (const url of urls) {
    try {
      const res = await indexing.urlNotifications.publish({
        requestBody: {
          url,
          type: "URL_UPDATED",
        },
      });
      console.log(`  ✓ ${url} → ${res.data.urlNotificationMetadata?.latestUpdate?.type || "OK"}`);
      success++;
    } catch (err) {
      console.error(`  ✗ ${url} → ${err.message}`);
      failed++;
    }

    // Rate limit: 1 req/sec
    await new Promise(r => setTimeout(r, 1100));
  }

  console.log(`\n完了: 成功=${success} 失敗=${failed}\n`);
}

main().catch(err => {
  console.error("エラー:", err.message);
  process.exit(1);
});
