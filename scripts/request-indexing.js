#!/usr/bin/env node

/**
 * Google Indexing API — URL一括インデックスリクエスト
 *
 * 使い方:
 *   node scripts/request-indexing.js                       # sitemap.xml の全URLをリクエスト（推奨）
 *   node scripts/request-indexing.js --filter articles     # /articles/ を含むURLのみ
 *   node scripts/request-indexing.js --filter category     # /category/ のみ
 *   node scripts/request-indexing.js --limit 50            # 上限指定
 *   node scripts/request-indexing.js --dry-run             # 確認のみ
 *   node scripts/request-indexing.js --urls url1 url2      # 指定URLのみ
 *
 * Indexing API クォータ: デフォルト 200 req/day
 */

import { google } from "googleapis";
import fs from "node:fs";
import path from "node:path";
import { loadEnv } from "../src/lib/x-agent-utils.mjs";

loadEnv();

const SITEMAP_URL = "https://camp-gear-lab.com/sitemap.xml";
const LOG_PATH = path.join(process.cwd(), "data", "seo-indexing-log.json");
const RATE_LIMIT_MS = 1100; // 1 req/sec

// ─── CLI ─────────────────────────────────────────────

function parseArgs() {
  const args = process.argv.slice(2);
  const opts = { filter: null, limit: Infinity, dryRun: false, urls: null };
  for (let i = 0; i < args.length; i++) {
    const a = args[i];
    if (a === "--filter") opts.filter = args[++i];
    else if (a === "--limit") opts.limit = parseInt(args[++i], 10) || Infinity;
    else if (a === "--dry-run") opts.dryRun = true;
    else if (a === "--urls") {
      opts.urls = args.slice(i + 1).filter((u) => u.startsWith("http"));
      break;
    }
  }
  return opts;
}

// ─── URL取得 ─────────────────────────────────────────

async function fetchSitemapUrls() {
  const res = await fetch(`${SITEMAP_URL}?_cb=${Date.now()}`, {
    cache: "no-store",
    headers: { "Cache-Control": "no-cache" },
  });
  if (!res.ok) throw new Error(`sitemap fetch ${res.status}`);
  const xml = await res.text();
  const matches = [...xml.matchAll(/<loc>([^<]+)<\/loc>/g)];
  return matches.map((m) => m[1].trim()).filter((u) => u.startsWith("http"));
}

const BASE_URL = "https://camp-gear-lab.com";

function readLocalData() {
  const articles = JSON.parse(fs.readFileSync("data/articles.json", "utf8"));
  const categories = JSON.parse(fs.readFileSync("data/categories.json", "utf8"));
  const published = articles.filter((a) => a.status === "published");
  const usedCategoryIds = new Set(published.map((a) => a.categoryId));
  return {
    articles,
    // 公開記事が1本も無いカテゴリはページ自体が404を返す（サイト側で
    // 薄いページを出さないようにしているため）。送信対象から外す
    liveCategories: categories.filter((c) => usedCategoryIds.has(c.id)),
    publishedSlugs: new Set(published.map((a) => a.slug)),
    knownSlugs: new Set(articles.map((a) => a.slug)),
    knownCategorySlugs: new Set(categories.map((c) => c.slug)),
    liveCategorySlugs: new Set(
      categories.filter((c) => usedCategoryIds.has(c.id)).map((c) => c.slug)
    ),
  };
}

function fetchUrlsFromLocalData(local) {
  // sitemap が CDN キャッシュされている場合に備えてローカルJSONからも生成
  const urls = [BASE_URL];
  for (const c of local.liveCategories) urls.push(`${BASE_URL}/category/${c.slug}`);
  for (const slug of local.publishedSlugs) urls.push(`${BASE_URL}/articles/${slug}`);
  return urls;
}

// 本番のsitemapはCDNキャッシュで古いことがあり、非公開化・統合した記事の
// URLが残る。Googleに301や404を送るのは無駄なので、ローカルデータで
// 「存在は知っているが今は公開されていない」と判定できるURLだけ落とす。
// ローカルに無いURL（新規追加など）は判断できないので残す
function dropStaleUrls(urls, local) {
  const dropped = [];
  const kept = urls.filter((u) => {
    const art = u.match(/\/articles\/([^/?#]+)\/?$/);
    if (art && local.knownSlugs.has(art[1]) && !local.publishedSlugs.has(art[1])) {
      dropped.push(u);
      return false;
    }
    const cat = u.match(/\/category\/([^/?#]+)\/?$/);
    if (
      cat &&
      local.knownCategorySlugs.has(cat[1]) &&
      !local.liveCategorySlugs.has(cat[1])
    ) {
      dropped.push(u);
      return false;
    }
    return true;
  });
  if (dropped.length > 0) {
    console.log(
      `[index-now] 非公開・空カテゴリのURLを除外: ${dropped.length}件`
    );
    for (const u of dropped) console.log(`  - ${u}`);
  }
  return kept;
}

async function getUrls(opts) {
  if (opts.urls && opts.urls.length > 0) return opts.urls;

  let sitemapUrls = [];
  try {
    sitemapUrls = await fetchSitemapUrls();
    console.log(`[index-now] sitemap urls: ${sitemapUrls.length}`);
  } catch (err) {
    console.warn(`[index-now] sitemap fetch failed: ${err.message}`);
  }

  const local = readLocalData();
  const localUrls = fetchUrlsFromLocalData(local);
  console.log(`[index-now] local urls: ${localUrls.length}`);

  // sitemap と local をマージ（ローカルの方が新しい可能性があるため和集合）。
  // そのうえで、古いsitemapに残った非公開・空カテゴリのURLを落とす
  const merged = dropStaleUrls(
    Array.from(new Set([...sitemapUrls, ...localUrls])),
    local
  );
  console.log(`[index-now] merged unique urls: ${merged.length}`);
  return merged;
}

// ─── Indexing API ────────────────────────────────────

async function publishUrl(indexing, url) {
  try {
    const res = await indexing.urlNotifications.publish({
      requestBody: { url, type: "URL_UPDATED" },
    });
    return { ok: true, status: 200, body: res.data?.urlNotificationMetadata?.latestUpdate?.type || "OK" };
  } catch (err) {
    return { ok: false, status: err.code || 0, body: err.message?.slice(0, 200) || "error" };
  }
}

// ─── メイン ─────────────────────────────────────────

async function main() {
  const opts = parseArgs();
  let urls = await getUrls(opts);

  if (opts.filter) {
    urls = urls.filter((u) => u.includes(opts.filter));
    console.log(`[index-now] filtered "${opts.filter}": ${urls.length}`);
  }
  if (urls.length > opts.limit) {
    urls = urls.slice(0, opts.limit);
    console.log(`[index-now] limited to ${opts.limit}`);
  }

  console.log(`\n=== Indexing API リクエスト ${opts.dryRun ? "(DRY RUN)" : ""} ===`);
  console.log(`対象: ${urls.length}件\n`);

  if (opts.dryRun) {
    urls.forEach((u) => console.log(`  [DRY] ${u}`));
    return;
  }

  const credentials = JSON.parse(process.env.INDEXING_CREDENTIALS || "{}");
  if (!credentials.client_email) {
    console.error("[index-now] INDEXING_CREDENTIALS 未設定または無効");
    process.exit(1);
  }
  const auth = new google.auth.GoogleAuth({
    credentials,
    scopes: ["https://www.googleapis.com/auth/indexing"],
  });
  const indexing = google.indexing({ version: "v3", auth });

  const log = { startedAt: new Date().toISOString(), results: [] };
  let success = 0;
  let failed = 0;
  let quotaExceeded = false;

  for (let i = 0; i < urls.length; i++) {
    const url = urls[i];
    const r = await publishUrl(indexing, url);
    log.results.push({ url, ...r });
    if (r.ok) {
      success++;
      console.log(`[${i + 1}/${urls.length}] ✓ ${url}`);
    } else {
      failed++;
      console.warn(`[${i + 1}/${urls.length}] ✗ ${r.status} ${url} :: ${r.body}`);
      if (r.status === 429 || r.body?.includes("quota")) {
        console.warn("[index-now] クォータ上限到達 — 中断");
        quotaExceeded = true;
        break;
      }
      if (r.status === 403) {
        console.warn("[index-now] 403 — service account を Search Console の「所有者」に追加してください");
      }
    }
    await new Promise((r) => setTimeout(r, RATE_LIMIT_MS));
  }

  log.finishedAt = new Date().toISOString();
  log.summary = { success, failed, quotaExceeded, total: urls.length };
  fs.mkdirSync(path.dirname(LOG_PATH), { recursive: true });
  fs.writeFileSync(LOG_PATH, JSON.stringify(log, null, 2));

  console.log(`\n[index-now] 完了: 成功=${success} 失敗=${failed} / 全${urls.length}`);
  console.log(`[index-now] ログ: ${LOG_PATH}`);
}

main().catch((err) => {
  console.error("[index-now] エラー:", err.message);
  process.exit(1);
});
