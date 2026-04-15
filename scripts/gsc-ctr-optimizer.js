#!/usr/bin/env node
/**
 * GSC CTR 最適化スクリプト
 *
 * Google Search Console からクエリデータを取得し、
 * 表示回数が多いのにクリック率が低いページを特定して
 * Claude で改善タイトル・メタディスクリプションを生成する。
 *
 * 使い方:
 *   node scripts/gsc-ctr-optimizer.js              # 上位20ページを分析
 *   node scripts/gsc-ctr-optimizer.js --top=50     # 上位50ページ
 *   node scripts/gsc-ctr-optimizer.js --dry-run    # 分析のみ（生成なし）
 *   node scripts/gsc-ctr-optimizer.js --apply      # articles.json に書き戻し
 */

import { google } from "googleapis";
import Anthropic from "@anthropic-ai/sdk";
import fs from "fs";
import path from "path";
import { fileURLToPath } from "url";
import { loadEnv, readJson } from "../src/lib/x-agent-utils.mjs";

loadEnv();

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const DATA_DIR = path.join(__dirname, "..", "data");
const SITE_URL = "https://camp-gear-lab.com/";

// CLI引数
const args = process.argv.slice(2);
const dryRun = args.includes("--dry-run");
const applyChanges = args.includes("--apply");
const topArg = args.find((a) => a.startsWith("--top="));
const TOP_N = topArg ? parseInt(topArg.split("=")[1], 10) : 20;

// ─── Google 認証 ───────────────────────────────────────────

function getGoogleAuth() {
  const creds = JSON.parse(process.env.GOOGLE_CREDENTIALS || "null");
  if (!creds) throw new Error("GOOGLE_CREDENTIALS が未設定です");
  return new google.auth.GoogleAuth({
    credentials: creds,
    scopes: ["https://www.googleapis.com/auth/webmasters.readonly"],
  });
}

// ─── Search Console データ取得 ──────────────────────────────

async function fetchGscData(auth, days = 90) {
  const sc = google.searchconsole({ version: "v1", auth });
  const endDate = new Date().toISOString().slice(0, 10);
  const startDate = new Date(Date.now() - days * 86400000).toISOString().slice(0, 10);

  const res = await sc.searchanalytics.query({
    siteUrl: SITE_URL,
    requestBody: {
      startDate,
      endDate,
      dimensions: ["page"],
      rowLimit: 500,
    },
  });

  return res.data.rows || [];
}

// ─── 改善候補の特定 ────────────────────────────────────────

function findLowCtrPages(rows, topN) {
  // impressions >= 50 && ctr < 3% を「改善余地あり」とみなす
  const candidates = rows
    .filter((r) => r.impressions >= 50 && r.ctr < 0.03)
    .sort((a, b) => b.impressions - a.impressions)
    .slice(0, topN);

  return candidates;
}

// ─── 記事データとマッチング ────────────────────────────────

function matchArticles(candidates, articles) {
  return candidates.map((row) => {
    const pageUrl = row.keys[0];
    const slug = pageUrl.replace(SITE_URL, "").replace(/\/$/, "").replace(/^\//, "");
    const article = articles.find((a) => a.slug === slug);
    return {
      url: pageUrl,
      slug,
      impressions: Math.round(row.impressions),
      clicks: Math.round(row.clicks),
      ctr: (row.ctr * 100).toFixed(2),
      position: row.position.toFixed(1),
      currentTitle: article?.title || "(不明)",
      currentMeta: article?.metaDescription || "",
      article,
    };
  });
}

// ─── Claude で改善案生成 ───────────────────────────────────

async function generateImprovements(client, pages) {
  const pageList = pages
    .map(
      (p, i) =>
        `${i + 1}. URL: ${p.url}\n   現タイトル: ${p.currentTitle}\n   現メタ: ${p.currentMeta || "(未設定)"}\n   表示回数: ${p.impressions}回 / CTR: ${p.ctr}% / 平均順位: ${p.position}位`
    )
    .join("\n\n");

  const prompt = `あなたはSEOとコンテンツ最適化の専門家です。
キャンプ・アウトドアギアの比較アフィリエイトサイト「camp-gear-lab.com」の記事タイトルとメタディスクリプションを改善してください。

## 改善の方向性
- クリック率（CTR）を上げるために、検索意図に刺さるタイトルにする
- 「比較」「選び方」「おすすめ」などのキーワードを自然に含める
- タイトルは30〜35文字程度（日本語）
- メタディスクリプションは110〜120文字程度
- 「最高」「完全版」など誇大表現は使わない
- 具体的な数字・固有名詞があると強い（「3選」「スノーピーク vs コールマン」等）

## 対象ページ

${pageList}

## 出力形式（JSON配列）

\`\`\`json
[
  {
    "slug": "記事スラッグ",
    "title": "改善後タイトル",
    "metaDescription": "改善後メタディスクリプション（110〜120文字）",
    "reason": "改善のポイント（1行）"
  }
]
\`\`\``;

  const response = await client.messages.create({
    model: "claude-sonnet-4-6",
    max_tokens: 4000,
    messages: [{ role: "user", content: prompt }],
  });

  const text = response.content[0].text;
  const match = text.match(/```json\n?([\s\S]*?)\n?```/);
  if (!match) throw new Error("JSONが見つかりません");
  return JSON.parse(match[1]);
}

// ─── articles.json への書き戻し ────────────────────────────

function applyToArticles(improvements, articles) {
  let count = 0;
  for (const imp of improvements) {
    const idx = articles.findIndex((a) => a.slug === imp.slug);
    if (idx === -1) continue;
    articles[idx].title = imp.title;
    articles[idx].metaDescription = imp.metaDescription;
    count++;
  }
  return count;
}

// ─── メイン ───────────────────────────────────────────────

async function main() {
  const apiKey = process.env.ANTHROPIC_API_KEY;
  if (!apiKey) throw new Error("ANTHROPIC_API_KEY が未設定です");

  console.log(`GSC CTR 最適化 (top=${TOP_N}, dry-run=${dryRun}, apply=${applyChanges})`);

  // Search Console データ取得
  console.log("\n[1] Search Console からデータ取得中...");
  const auth = getGoogleAuth();
  const rows = await fetchGscData(auth);
  console.log(`  ${rows.length}件のページデータを取得`);

  // 改善候補の特定
  const candidates = findLowCtrPages(rows, TOP_N);
  console.log(`  改善候補: ${candidates.length}件 (impressions≥50 && CTR<3%)`);

  // 記事データとマッチング
  const articlesData = readJson("articles.json");
  const articles = articlesData.articles || articlesData;
  const pages = matchArticles(candidates, articles);

  console.log("\n[2] 改善候補ページ:");
  pages.forEach((p, i) => {
    console.log(`  ${i + 1}. [${p.impressions}imp / CTR:${p.ctr}% / 順位:${p.position}] ${p.currentTitle}`);
    console.log(`     ${p.url}`);
  });

  if (dryRun || pages.length === 0) {
    console.log("\n[DRY-RUN] 生成をスキップしました");
    return;
  }

  // Claude で改善案生成
  console.log("\n[3] Claude で改善案を生成中...");
  const client = new Anthropic({ apiKey });
  const improvements = await generateImprovements(client, pages);

  console.log("\n[4] 生成結果:");
  improvements.forEach((imp) => {
    const page = pages.find((p) => p.slug === imp.slug);
    console.log(`\n  slug: ${imp.slug}`);
    console.log(`  Before: ${page?.currentTitle || "-"}`);
    console.log(`  After:  ${imp.title}`);
    console.log(`  Meta:   ${imp.metaDescription}`);
    console.log(`  理由:   ${imp.reason}`);
  });

  // レポート保存
  const report = {
    generatedAt: new Date().toISOString(),
    totalCandidates: candidates.length,
    improvements,
  };
  const reportPath = path.join(DATA_DIR, "gsc-ctr-report.json");
  fs.writeFileSync(reportPath, JSON.stringify(report, null, 2));
  console.log(`\n  → ${reportPath} に保存しました`);

  // articles.json への書き戻し
  if (applyChanges) {
    console.log("\n[5] articles.json に書き戻し中...");
    const allArticles = articlesData.articles || articlesData;
    const count = applyToArticles(improvements, allArticles);
    const outData = articlesData.articles ? { ...articlesData, articles: allArticles } : allArticles;
    const articlesPath = path.join(DATA_DIR, "articles.json");
    fs.writeFileSync(articlesPath, JSON.stringify(outData, null, 2));
    console.log(`  → ${count}件のタイトル/メタを更新しました`);
  } else {
    console.log("\n  ※ --apply を付けると articles.json に書き戻します");
  }
}

main().catch((err) => {
  console.error("エラー:", err.message);
  process.exit(1);
});
