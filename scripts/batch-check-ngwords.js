#!/usr/bin/env node
/**
 * 記事本文のNGワード・AI臭い表現をバッチ検査するスクリプト
 *
 * 使い方:
 *   node scripts/batch-check-ngwords.js              (全公開記事)
 *   node scripts/batch-check-ngwords.js --all         (ドラフト含む全件)
 *   node scripts/batch-check-ngwords.js --slug=xxx    (1件のみ)
 *
 * 結果: data/article-quality-report.json に出力
 */

import fs from "fs";
import path from "path";
import { fileURLToPath } from "url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const DATA_DIR = path.join(__dirname, "..", "data");
const INCLUDE_DRAFTS = process.argv.includes("--all");
const TARGET_SLUG = process.argv.find((a) => a.startsWith("--slug="))?.split("=")[1];

// ============================================================
// NGワード定義（記事本文向け）
// ============================================================

/** HIGH: 薬機法・医療法系（掲載不可レベル） */
const NG_HIGH = [
  "ガンに効く", "病気が治る", "アレルギーが治", "副作用なし", "医師推奨",
  "改善する", "改善できる", "予防できます", "診断", "処方", "治療法",
  "療法として", "治る", "治します", "痩せる", "飲んでください", "服用して",
];

/** MEDIUM: AI臭い定型表現（人間レビュー推奨） */
const NG_MEDIUM = [
  "かもしれません",
  "することができます",
  "と言えるでしょう",
  "において",
  "に関して",
  "が期待できます",
  "それでは.*を見ていきましょう",
  "ご紹介します",
  "ということになります",
  "という点で",
  "という観点から",
  "ではないでしょうか",
  "していただける",
  "していただきましょう",
];

/** LOW: 過剰表現・NG感情語 */
const NG_LOW = [
  "素晴らしい",
  "最高の",
  "革命",
  "奇跡",
  "神ギア",
  "圧倒的",
  "絶対に",
  "間違いなく",
  "業界No\\.1",
  "今すぐ買え",
];

// ============================================================
// チェック処理
// ============================================================

function checkContent(content = "") {
  const issues = [];

  for (const pattern of NG_HIGH) {
    const re = new RegExp(pattern, "g");
    const matches = [...content.matchAll(re)];
    if (matches.length > 0) {
      issues.push({ level: "HIGH", pattern, count: matches.length });
    }
  }

  for (const pattern of NG_MEDIUM) {
    const re = new RegExp(pattern, "g");
    const matches = [...content.matchAll(re)];
    if (matches.length > 0) {
      issues.push({ level: "MEDIUM", pattern, count: matches.length });
    }
  }

  for (const pattern of NG_LOW) {
    const re = new RegExp(pattern, "g");
    const matches = [...content.matchAll(re)];
    if (matches.length > 0) {
      issues.push({ level: "LOW", pattern, count: matches.length });
    }
  }

  return issues;
}

// ============================================================
// メイン処理
// ============================================================

const articles = JSON.parse(fs.readFileSync(path.join(DATA_DIR, "articles.json"), "utf-8"));

let targets = articles.filter(
  (a) => (INCLUDE_DRAFTS || a.status === "published") && (!TARGET_SLUG || a.slug === TARGET_SLUG)
);

const report = {
  generatedAt: new Date().toISOString(),
  totalChecked: targets.length,
  results: [],
};

let totalHigh = 0, totalMedium = 0, totalLow = 0;

for (const article of targets) {
  const issues = checkContent(article.content);
  if (issues.length === 0) continue;

  const high = issues.filter((i) => i.level === "HIGH");
  const medium = issues.filter((i) => i.level === "MEDIUM");
  const low = issues.filter((i) => i.level === "LOW");
  totalHigh += high.length;
  totalMedium += medium.length;
  totalLow += low.length;

  report.results.push({
    slug: article.slug,
    title: article.title,
    status: article.status,
    highCount: high.length,
    mediumCount: medium.length,
    lowCount: low.length,
    issues,
  });
}

// HIGH優先でソート
report.results.sort((a, b) => b.highCount - a.highCount || b.mediumCount - a.mediumCount);

// ============================================================
// コンソール出力
// ============================================================

console.log(`\n📋 記事NGワード検査レポート`);
console.log(`   対象: ${targets.length}件 / 問題あり: ${report.results.length}件`);
console.log(`   HIGH: ${totalHigh}件  MEDIUM: ${totalMedium}件  LOW: ${totalLow}件\n`);

for (const r of report.results) {
  const badge = r.highCount > 0 ? "🔴 HIGH" : r.mediumCount > 0 ? "🟡 MEDIUM" : "🟢 LOW";
  console.log(`${badge}  ${r.slug}`);
  console.log(`   ${r.title?.slice(0, 50)}`);
  for (const issue of r.issues) {
    const icon = issue.level === "HIGH" ? "❌" : issue.level === "MEDIUM" ? "⚠️ " : "ℹ️ ";
    console.log(`   ${icon} [${issue.level}] "${issue.pattern}" × ${issue.count}回`);
  }
  console.log();
}

// ============================================================
// レポート保存
// ============================================================

fs.writeFileSync(path.join(DATA_DIR, "article-quality-report.json"), JSON.stringify(report, null, 2));
console.log(`✅ レポート保存: data/article-quality-report.json`);
