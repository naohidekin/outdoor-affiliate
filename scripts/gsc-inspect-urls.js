#!/usr/bin/env node

/**
 * GSC URL Inspection — 全URLのインデックス状態を一括チェック
 *
 * 使い方:
 *   node scripts/gsc-inspect-urls.js                    # サイトマップ+ローカルの全URL
 *   node scripts/gsc-inspect-urls.js --deleted-only     # 削除済みスラッグのみ
 *   node scripts/gsc-inspect-urls.js --limit 10         # 件数制限
 *   node scripts/gsc-inspect-urls.js --urls url1 url2   # 指定URLのみ
 *
 * URL Inspection API クォータ: 2,000 req/day/property
 */

import { google } from "googleapis";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { loadEnv } from "../src/lib/x-agent-utils.mjs";

loadEnv();

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const SITE_URL = "https://camp-gear-lab.com";
const OUTPUT_PATH = path.join(process.cwd(), "data", "gsc-inspection-results.json");
const RATE_LIMIT_MS = 600; // 1.5 req/sec (quota = 2000/day)

// ─── CLI ─────────────────────────────────────────────

function parseArgs() {
  const args = process.argv.slice(2);
  const opts = { deletedOnly: false, limit: Infinity, urls: null };
  for (let i = 0; i < args.length; i++) {
    const a = args[i];
    if (a === "--deleted-only") opts.deletedOnly = true;
    else if (a === "--limit") opts.limit = parseInt(args[++i], 10) || Infinity;
    else if (a === "--urls") {
      opts.urls = args.slice(i + 1).filter((u) => u.startsWith("http"));
      break;
    }
  }
  return opts;
}

// ─── URL収集 ─────────────────────────────────────────

function getPublishedUrls() {
  const articles = JSON.parse(fs.readFileSync("data/articles.json", "utf8"));
  const categories = JSON.parse(fs.readFileSync("data/categories.json", "utf8"));
  const urls = [SITE_URL];
  for (const c of categories) urls.push(`${SITE_URL}/category/${c.slug}`);
  for (const a of articles) {
    if (a.status === "published") urls.push(`${SITE_URL}/articles/${a.slug}`);
  }
  return urls;
}

function getDeletedSlugs() {
  // articles.jsonに存在するがdraftのもの + 過去に削除されたと推測されるもの
  const articles = JSON.parse(fs.readFileSync("data/articles.json", "utf8"));
  const draftSlugs = articles.filter((a) => a.status !== "published").map((a) => a.slug);

  // 過去に存在して現在完全削除されたスラッグ（git履歴から特定済み）
  const historicallyDeleted = [
    "camp-insect-repellent-roadmap",
    "camp-night-toilet-light-guide",
    "family-camp-budget-guide",
    "family-camp-chair-ranking",
    "kids-insect-repellent-guide",
    "kids-insect-repellent-ranking",
    "quick-dry-tshirt-ranking",
    "rain-proof-tent-ranking",
    "solo-camp-chair-ranking",
    "spring-camp-cold-kids-guide",
    "spring-camp-tent-guide",
    "summer-camp-heat-food-safety",
    "tarp-setup-patterns-guide",
    "tarp-tent-connection-setup-guide",
    "tent-without-vestibule-guide",
    "winter-camp-co-safety-guide",
    "2-person-tent-ranking",
  ];

  const allDeleted = [...new Set([...draftSlugs, ...historicallyDeleted])];
  return allDeleted.map((slug) => `${SITE_URL}/articles/${slug}`);
}

// ─── URL Inspection API ──────────────────────────────

async function inspectUrl(searchconsole, url) {
  try {
    const res = await searchconsole.urlInspection.index.inspect({
      requestBody: {
        inspectionUrl: url,
        siteUrl: `${SITE_URL}/`,
      },
    });

    const result = res.data?.inspectionResult;
    const indexStatus = result?.indexStatusResult;
    const crawlInfo = indexStatus?.crawledAs;
    const verdict = indexStatus?.verdict; // PASS, PARTIAL, FAIL, NEUTRAL
    const coverageState = indexStatus?.coverageState; // e.g., "Submitted and indexed", "Crawled - currently not indexed"
    const pageFetchState = indexStatus?.pageFetchState; // e.g., "SUCCESSFUL", "SOFT_404"
    const robotsTxtState = indexStatus?.robotsTxtState; // e.g., "ALLOWED"
    const lastCrawlTime = indexStatus?.lastCrawlTime;
    const referringUrls = indexStatus?.referringUrls;

    return {
      url,
      verdict,
      coverageState,
      pageFetchState,
      robotsTxtState,
      crawledAs: crawlInfo,
      lastCrawlTime,
      referringUrls: referringUrls || [],
      error: null,
    };
  } catch (err) {
    return {
      url,
      verdict: null,
      coverageState: null,
      pageFetchState: null,
      robotsTxtState: null,
      crawledAs: null,
      lastCrawlTime: null,
      referringUrls: [],
      error: err.message?.slice(0, 300) || "unknown error",
    };
  }
}

// ─── メイン ──────────────────────────────────────────

async function main() {
  const opts = parseArgs();

  let urls;
  if (opts.urls && opts.urls.length > 0) {
    urls = opts.urls;
  } else if (opts.deletedOnly) {
    urls = getDeletedSlugs();
    console.log(`[gsc-inspect] 削除済み/draft URL: ${urls.length}件`);
  } else {
    const published = getPublishedUrls();
    const deleted = getDeletedSlugs();
    urls = [...published, ...deleted];
    console.log(`[gsc-inspect] 公開URL: ${published.length}件 + 削除/draft: ${deleted.length}件 = 合計: ${urls.length}件`);
  }

  if (urls.length > opts.limit) {
    urls = urls.slice(0, opts.limit);
    console.log(`[gsc-inspect] ${opts.limit}件に制限`);
  }

  // Auth
  const credentials = JSON.parse(process.env.INDEXING_CREDENTIALS || "{}");
  if (!credentials.client_email) {
    console.error("[gsc-inspect] INDEXING_CREDENTIALS 未設定");
    process.exit(1);
  }

  const auth = new google.auth.GoogleAuth({
    credentials,
    scopes: [
      "https://www.googleapis.com/auth/webmasters",
      "https://www.googleapis.com/auth/webmasters.readonly",
    ],
  });
  const searchconsole = google.searchconsole({ version: "v1", auth });

  console.log(`\n=== GSC URL Inspection ===\n`);

  const results = [];
  const summary = { indexed: 0, notIndexed: 0, error404: 0, other: 0, apiError: 0 };

  for (let i = 0; i < urls.length; i++) {
    const url = urls[i];
    const r = await inspectUrl(searchconsole, url);
    results.push(r);

    const icon = r.error
      ? "⚠"
      : r.verdict === "PASS"
        ? "✓"
        : r.pageFetchState === "SOFT_404" || r.coverageState?.includes("404")
          ? "✗"
          : "○";

    console.log(
      `[${i + 1}/${urls.length}] ${icon} ${url.replace(SITE_URL, "")} → ${r.coverageState || r.error || "unknown"}`
    );

    // Summary
    if (r.error) summary.apiError++;
    else if (r.verdict === "PASS") summary.indexed++;
    else if (r.pageFetchState === "SOFT_404" || r.coverageState?.includes("404")) summary.error404++;
    else if (r.verdict === "FAIL" || r.verdict === "NEUTRAL") summary.notIndexed++;
    else summary.other++;

    if (i < urls.length - 1) await new Promise((resolve) => setTimeout(resolve, RATE_LIMIT_MS));
  }

  // Output
  const output = {
    inspectedAt: new Date().toISOString(),
    totalUrls: urls.length,
    summary,
    results,
  };

  fs.writeFileSync(OUTPUT_PATH, JSON.stringify(output, null, 2));

  console.log(`\n=== サマリー ===`);
  console.log(`インデックス済み: ${summary.indexed}`);
  console.log(`未インデックス:   ${summary.notIndexed}`);
  console.log(`404エラー:        ${summary.error404}`);
  console.log(`その他:           ${summary.other}`);
  console.log(`APIエラー:        ${summary.apiError}`);
  console.log(`\n結果保存: ${OUTPUT_PATH}`);

  // 問題URLだけ再表示
  const problems = results.filter((r) => r.verdict !== "PASS" && !r.error);
  if (problems.length > 0) {
    console.log(`\n=== 問題URL一覧 (${problems.length}件) ===`);
    for (const p of problems) {
      console.log(`  ${p.url.replace(SITE_URL, "")}`);
      console.log(`    状態: ${p.coverageState} | フェッチ: ${p.pageFetchState} | robots: ${p.robotsTxtState}`);
      if (p.lastCrawlTime) console.log(`    最終クロール: ${p.lastCrawlTime}`);
    }
  }
}

main().catch((err) => {
  console.error("[gsc-inspect] エラー:", err.message);
  process.exit(1);
});
