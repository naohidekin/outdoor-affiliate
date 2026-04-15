#!/usr/bin/env node
/**
 * GSC CTR 最適化スクリプト
 *
 * Google Search Console からエクスポートした CSV を読み込み、
 * 表示回数が多いのにクリック率が低いページを特定して
 * Claude で改善タイトル・メタディスクリプションを生成する。
 *
 * 使い方:
 *   1. Search Console → 検索パフォーマンス → ページ → エクスポート → CSV
 *   2. CSVを data/gsc-export.csv に配置
 *   3. node scripts/gsc-ctr-optimizer.js --dry-run   # 分析のみ
 *      node scripts/gsc-ctr-optimizer.js             # 改善案生成
 *      node scripts/gsc-ctr-optimizer.js --apply     # articles.json に書き戻し
 *
 * CSVの列: ページ, クリック数, 表示回数, CTR, 掲載順位
 */

import Anthropic from "@anthropic-ai/sdk";
import fs from "fs";
import path from "path";
import { fileURLToPath } from "url";
import { loadEnv, readJson } from "../src/lib/x-agent-utils.mjs";

loadEnv();

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const DATA_DIR = path.join(__dirname, "..", "data");
const SITE_URL = "https://camp-gear-lab.com";

// CLI引数
const args = process.argv.slice(2);
const dryRun = args.includes("--dry-run");
const applyChanges = args.includes("--apply");
const topArg = args.find((a) => a.startsWith("--top="));
const TOP_N = topArg ? parseInt(topArg.split("=")[1], 10) : 20;

// ─── CSV パース ────────────────────────────────────────────

function parseGscCsv(csvPath) {
  const text = fs.readFileSync(csvPath, "utf-8");
  const lines = text.split("\n").filter((l) => l.trim());

  // ヘッダー行をスキップ（先頭がURLでないもの）
  const dataLines = lines.filter((l) => l.startsWith("https://"));

  return dataLines.map((line) => {
    // CSV のカンマはURL内に含まれないので単純分割でOK
    const cols = line.split(",");
    const url = cols[0].trim();
    const clicks = parseInt(cols[1]?.trim() || "0", 10);
    const impressions = parseInt(cols[2]?.trim() || "0", 10);
    // CTR は "1.2%" または "0.012" の両形式に対応
    const ctrRaw = cols[3]?.trim().replace("%", "") || "0";
    const ctr = parseFloat(ctrRaw) > 1 ? parseFloat(ctrRaw) / 100 : parseFloat(ctrRaw);
    const position = parseFloat(cols[4]?.trim() || "0");
    return { url, clicks, impressions, ctr, position };
  });
}

// ─── 改善候補の特定 ────────────────────────────────────────

function findLowCtrPages(rows, topN) {
  return rows
    .filter((r) => r.impressions >= 30 && r.ctr < 0.04)
    .sort((a, b) => b.impressions - a.impressions)
    .slice(0, topN);
}

// ─── 記事データとマッチング ────────────────────────────────

function matchArticles(candidates, articles) {
  return candidates.map((row) => {
    const slug = row.url
      .replace(SITE_URL, "")
      .replace(/\/$/, "")
      .replace(/^\//, "")
      .replace(/^articles\//, "");
    const article = articles.find((a) => a.slug === slug);
    return {
      url: row.url,
      slug,
      impressions: row.impressions,
      clicks: row.clicks,
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
        `${i + 1}. スラッグ: ${p.slug}\n   現タイトル: ${p.currentTitle}\n   現メタ: ${p.currentMeta || "(未設定)"}\n   表示回数: ${p.impressions}回 / CTR: ${p.ctr}% / 平均順位: ${p.position}位`
    )
    .join("\n\n");

  const prompt = `あなたはSEOとコンテンツ最適化の専門家です。
キャンプ・アウトドアギアの比較アフィリエイトサイト「camp-gear-lab.com」の記事タイトルとメタディスクリプションを改善してください。

## 改善の方向性
- クリック率（CTR）を上げるために、検索意図に刺さるタイトルにする
- 「比較」「選び方」「おすすめ」などのキーワードを自然に含める
- タイトルは28〜35文字程度（日本語）
- メタディスクリプションは110〜120文字程度
- 「最高」「完全版」など誇大表現は使わない
- 具体的な数字・固有名詞があると強い（「3選」「スノーピーク vs コールマン」等）
- 初心者〜中級者向けのサイトなので難しすぎる言葉は避ける

## 対象ページ

${pageList}

## 出力形式（JSON配列のみ・他のテキスト不要）

\`\`\`json
[
  {
    "slug": "記事スラッグ（変更不要）",
    "title": "改善後タイトル（28〜35文字）",
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
  if (!match) throw new Error("JSONが見つかりません:\n" + text.slice(0, 500));
  return JSON.parse(match[1]);
}

// ─── articles.json への書き戻し ────────────────────────────

function applyToArticles(improvements, articles) {
  let count = 0;
  for (const imp of improvements) {
    const idx = articles.findIndex((a) => a.slug === imp.slug);
    if (idx === -1) { console.warn(`  ⚠ slug not found: ${imp.slug}`); continue; }
    articles[idx].title = imp.title;
    articles[idx].metaDescription = imp.metaDescription;
    count++;
  }
  return count;
}

// ─── メイン ───────────────────────────────────────────────

async function main() {
  const csvPath = path.join(DATA_DIR, "gsc-export.csv");
  if (!fs.existsSync(csvPath)) {
    console.error(`
CSVファイルが見つかりません: ${csvPath}

手順:
  1. https://search.google.com/search-console/ を開く
  2. 検索パフォーマンス → ページタブ を選択
  3. 期間: 過去90日
  4. 右上「エクスポート」→「CSV」でダウンロード
  5. ダウンロードしたCSVを data/gsc-export.csv に配置
  6. 再度このスクリプトを実行
`);
    process.exit(1);
  }

  const apiKey = process.env.ANTHROPIC_API_KEY;
  if (!apiKey && !dryRun) throw new Error("ANTHROPIC_API_KEY が未設定です");

  console.log(`GSC CTR 最適化 (top=${TOP_N}, dry-run=${dryRun}, apply=${applyChanges})`);

  // CSV 読み込み
  console.log("\n[1] CSVを解析中...");
  const rows = parseGscCsv(csvPath);
  console.log(`  ${rows.length}件のページデータを読み込み`);

  // 改善候補の特定
  const candidates = findLowCtrPages(rows, TOP_N);
  console.log(`  改善候補: ${candidates.length}件 (impressions≥30 && CTR<4%)`);

  // 記事データとマッチング
  const articlesData = readJson("articles.json");
  const articles = articlesData.articles || articlesData;
  const pages = matchArticles(candidates, articles);

  console.log("\n[2] 改善候補ページ:");
  pages.forEach((p, i) => {
    console.log(`  ${i + 1}. [${p.impressions}imp / CTR:${p.ctr}% / 順位:${p.position}] ${p.currentTitle}`);
  });

  if (dryRun || pages.length === 0) {
    console.log("\n[DRY-RUN] 生成をスキップしました。--apply なしで実行すると改善案のみ表示します。");
    return;
  }

  // Claude で改善案生成
  console.log(`\n[3] Claude で ${pages.length}件の改善案を生成中...`);
  const client = new Anthropic({ apiKey });
  const improvements = await generateImprovements(client, pages);

  console.log("\n[4] 生成結果:");
  improvements.forEach((imp) => {
    const page = pages.find((p) => p.slug === imp.slug);
    console.log(`\n  ─ ${imp.slug}`);
    console.log(`  Before: ${page?.currentTitle || "-"}`);
    console.log(`  After:  ${imp.title}`);
    console.log(`  Meta:   ${imp.metaDescription}`);
    console.log(`  理由:   ${imp.reason}`);
  });

  // レポート保存
  const report = { generatedAt: new Date().toISOString(), totalCandidates: candidates.length, improvements };
  const reportPath = path.join(DATA_DIR, "gsc-ctr-report.json");
  fs.writeFileSync(reportPath, JSON.stringify(report, null, 2));
  console.log(`\n  → ${reportPath} に保存`);

  // articles.json への書き戻し
  if (applyChanges) {
    console.log("\n[5] articles.json に書き戻し中...");
    const allArticles = articlesData.articles || articlesData;
    const count = applyToArticles(improvements, allArticles);
    const outData = articlesData.articles ? { ...articlesData, articles: allArticles } : allArticles;
    fs.writeFileSync(path.join(DATA_DIR, "articles.json"), JSON.stringify(outData, null, 2));
    console.log(`  → ${count}件のタイトル/メタを更新しました`);
  } else {
    console.log("\n  ※ --apply を付けると articles.json に書き戻します");
  }
}

main().catch((err) => {
  console.error("エラー:", err.message);
  process.exit(1);
});
