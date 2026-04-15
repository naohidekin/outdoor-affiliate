#!/usr/bin/env node

/**
 * ニュースフィード取得スクリプト
 * RSS フィードを取得して data/news-feed.json にキャッシュする
 *
 * 使い方:
 *   node scripts/fetch-news.js             # 全フィード取得
 *   node scripts/fetch-news.js --dry-run   # 取得のみ、保存しない
 *   node scripts/fetch-news.js --limit=5   # 各フィードから最大5件
 */

import Parser from "rss-parser";
import fs from "fs";
import path from "path";
import crypto from "crypto";
import { fileURLToPath } from "url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const DATA_DIR = path.join(__dirname, "..", "data");
const NEWS_FEED_PATH = path.join(DATA_DIR, "news-feed.json");

const isDryRun = process.argv.includes("--dry-run");
const limitArg = process.argv.find((a) => a.startsWith("--limit="));
const LIMIT_PER_FEED = limitArg ? parseInt(limitArg.split("=")[1], 10) : 10;

/**
 * 取得対象 RSS フィード
 * キャンプ/アウトドア系メディア + NHK（安全・天気・国内ニュース用）
 */
const FEEDS = [
  {
    name: "BE-PAL",
    url: "https://www.bepal.net/feed",
    category: "outdoor-media",
  },
  {
    name: "CAMP HACK",
    url: "https://camphack.nap-camp.com/feed",
    category: "outdoor-media",
  },
  {
    name: "Google News - キャンプ",
    url: "https://news.google.com/rss/search?q=%E3%82%AD%E3%83%A3%E3%83%B3%E3%83%97&hl=ja&gl=JP&ceid=JP:ja",
    category: "google-news",
  },
  {
    name: "Google News - アウトドア",
    url: "https://news.google.com/rss/search?q=%E3%82%A2%E3%82%A6%E3%83%88%E3%83%89%E3%82%A2&hl=ja&gl=JP&ceid=JP:ja",
    category: "google-news",
  },
  {
    name: "NHK - 国内",
    url: "https://www3.nhk.or.jp/rss/news/cat0.xml",
    category: "news",
  },
];

/** ニュース系センシティブワード（取り込みをスキップ） */
const SKIP_KEYWORDS = [
  // 災害・安全系
  "地震", "津波", "台風", "洪水", "土砂", "噴火", "大雨", "避難",
  "死亡", "死者", "負傷", "けが人", "行方不明",
  // 社会・政治系
  "選挙", "国会", "首相", "大臣", "自民", "立憲", "共産", "公明",
  "逮捕", "起訴", "裁判", "有罪", "無罪",
  // 炎上・スキャンダル系
  "炎上", "謝罪", "不祥事", "スキャンダル", "事件",
];

function generateId(url) {
  return "news-" + crypto.createHash("md5").update(url).digest("hex").slice(0, 8);
}

function isSensitive(item) {
  const text = `${item.title || ""} ${item.contentSnippet || ""}`;
  return SKIP_KEYWORDS.some((kw) => text.includes(kw));
}

async function fetchFeed(feed) {
  const parser = new Parser({
    timeout: 10000,
    headers: { "User-Agent": "camp-gear-lab-bot/1.0" },
  });
  try {
    const result = await parser.parseURL(feed.url);
    const items = (result.items || []).slice(0, LIMIT_PER_FEED);
    return items.map((item) => ({
      id: generateId(item.link || item.guid || item.title || ""),
      title: item.title || "",
      url: item.link || item.guid || "",
      source: feed.name,
      category: feed.category,
      publishedAt: item.isoDate || item.pubDate || new Date().toISOString(),
      summary: (item.contentSnippet || "").slice(0, 200),
      fetchedAt: new Date().toISOString(),
      used: false,
      sensitive: isSensitive(item),
    }));
  } catch (err) {
    console.warn(`  [skip] ${feed.name}: ${err.message}`);
    return [];
  }
}

async function main() {
  console.log(`ニュースフィード取得開始 (dry-run=${isDryRun}, limit=${LIMIT_PER_FEED})`);

  // 既存キャッシュを読み込む（used フラグを維持するため）
  let existing = [];
  if (fs.existsSync(NEWS_FEED_PATH)) {
    existing = JSON.parse(fs.readFileSync(NEWS_FEED_PATH, "utf-8"));
  }
  const existingIds = new Set(existing.map((e) => e.id));

  const allNew = [];
  for (const feed of FEEDS) {
    process.stdout.write(`  ${feed.name} ... `);
    const items = await fetchFeed(feed);
    const fresh = items.filter((i) => !existingIds.has(i.id));
    console.log(`${fresh.length}件新着 (全${items.length}件)`);
    allNew.push(...fresh);
  }

  const sensitiveCount = allNew.filter((i) => i.sensitive).length;
  const usableCount = allNew.filter((i) => !i.sensitive).length;

  console.log(`\n合計: ${allNew.length}件新着 (センシティブ=${sensitiveCount}, 使用可能=${usableCount})`);

  if (isDryRun) {
    console.log("\n[DRY-RUN] 保存をスキップ。サンプル:");
    allNew.filter((i) => !i.sensitive).slice(0, 3).forEach((i) => {
      console.log(`  [${i.source}] ${i.title}`);
    });
    return;
  }

  // 既存 + 新着をマージ（重複排除）して保存
  // 古いものは30日経過したら削除（キャッシュ肥大化防止）
  const thirtyDaysAgo = new Date(Date.now() - 30 * 24 * 60 * 60 * 1000).toISOString();
  const merged = [
    ...existing.filter((e) => e.fetchedAt > thirtyDaysAgo),
    ...allNew,
  ];

  fs.writeFileSync(NEWS_FEED_PATH, JSON.stringify(merged, null, 2), "utf-8");
  console.log(`\nnews-feed.json を更新 (合計${merged.length}件)`);
}

main().catch((err) => {
  console.error("エラー:", err.message);
  process.exit(1);
});
