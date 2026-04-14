#!/usr/bin/env node

/**
 * Article Researcher Agent — テーマ選定（季節+GA4データ）
 *
 * 季節マッピング + Analystフィードバック + 既存記事の重複チェックから
 * 今週の3記事テーマを選定し article-weekly-plan.json に出力する。
 *
 * 使い方:
 *   node scripts/article-researcher-agent.js              # 週次プラン生成
 *   node scripts/article-researcher-agent.js --dry-run    # 表示のみ
 *   node scripts/article-researcher-agent.js --count 2    # 生成数指定
 */

import Anthropic from "@anthropic-ai/sdk";
import {
  loadEnv,
  readJson,
  writeJson,
  checkArticleKillSwitch,
} from "../src/lib/x-agent-utils.mjs";

loadEnv();

// ─── CLI ─────────────────────────────────────────────

function parseArgs() {
  const args = process.argv.slice(2);
  const opts = { dryRun: false, count: 3 };
  for (let i = 0; i < args.length; i++) {
    switch (args[i]) {
      case "--dry-run": opts.dryRun = true; break;
      case "--count":   opts.count = parseInt(args[++i], 10) || 3; break;
    }
  }
  return opts;
}

// ─── 週番号算出 ──────────────────────────────────────

function getWeekLabel() {
  const d = new Date();
  const utc = new Date(Date.UTC(d.getFullYear(), d.getMonth(), d.getDate()));
  const dayNum = utc.getUTCDay() || 7;
  utc.setUTCDate(utc.getUTCDate() + 4 - dayNum);
  const yearStart = new Date(Date.UTC(utc.getUTCFullYear(), 0, 1));
  const weekNo = Math.ceil(((utc - yearStart) / 86400000 + 1) / 7);
  return `${d.getFullYear()}-W${String(weekNo).padStart(2, "0")}`;
}

// ─── 公開スケジュール（水/金/日） ──────────────────

function getPublishDates(count) {
  const dates = [];
  const today = new Date();
  // 水曜(3)、金曜(5)、日曜(0) の順で次の該当日を取得
  const targetDays = [3, 5, 0]; // Wed, Fri, Sun

  for (let i = 1; dates.length < count; i++) {
    const d = new Date(today.getTime() + i * 86400000); // 毎回新規Date生成で月跨ぎ安全
    if (targetDays.includes(d.getDay())) {
      dates.push(d.toISOString().slice(0, 10));
    }
    if (i > 30) break; // safety
  }
  return dates;
}

// ─── メイン ──────────────────────────────────────────

async function main() {
  const opts = parseArgs();

  const ks = checkArticleKillSwitch();
  if (ks.killed) {
    console.error(`[article-researcher] ${ks.reason}`);
    process.exit(1);
  }

  console.log("[article-researcher] テーマ選定開始");

  // データ読み込み
  const categories = readJson("categories.json") || [];
  const articles = readJson("articles.json") || [];
  const seasonMap = readJson("article-season-map.json") || {};
  const feedback = readJson("article-analyst-feedback.json");

  const month = String(new Date().getMonth() + 1);
  const seasonCategories = seasonMap[month] || categories.map((c) => c.id);

  // 既存記事のスラッグ・カテゴリ分布
  const existingSlugs = articles.map((a) => a.slug);
  const existingByCategory = {};
  for (const a of articles) {
    if (!existingByCategory[a.categoryId]) existingByCategory[a.categoryId] = [];
    existingByCategory[a.categoryId].push(a.slug);
  }

  // Claude API でテーマ選定
  const anthropic = new Anthropic();

  const categoryList = categories
    .map((c) => `- ${c.id}: ${c.name} (${c.description})`)
    .join("\n");

  const seasonInfo = `今月(${month}月)の季節カテゴリ: ${seasonCategories.join(", ")}`;

  const existingArticleInfo = Object.entries(existingByCategory)
    .map(([cat, slugs]) => `  ${cat}: ${slugs.join(", ")}`)
    .join("\n");

  const analystInfo = feedback
    ? `\nAnalyst フィードバック:\n${JSON.stringify(feedback.categoryTrends || [], null, 2)}\n提案: ${(feedback.suggestions || []).join("; ")}`
    : "\nAnalyst フィードバック: なし（初回実行）";

  const systemPrompt = `あなたはアウトドア・キャンプ用品アフィリエイトサイト「camp-gear-lab.com」のコンテンツ戦略担当です。
週${opts.count}本の新規記事テーマを選定してください。

サイトのカテゴリ:
${categoryList}

${seasonInfo}

既存記事（重複を避けること）:
${existingArticleInfo}
${analystInfo}

ルール:
- 季節カテゴリを優先するが、データドリブンな判断も加味する
- 既存記事と同じ切り口は避け、新しい角度を提案する
- 各テーマに targetKeywords（2-3個）を付与する
- 初心者〜中級者が検索しそうなキーワードを想定する
- ${opts.count}記事を JSON 配列で返す`;

  const userPrompt = `今週の${opts.count}記事テーマを選定してください。

以下のJSON形式で返してください（コードブロック不要、JSON のみ）:
[
  {
    "categoryId": "カテゴリID",
    "title": "記事タイトル【2026年版】",
    "slug": "url-friendly-slug",
    "angle": "この記事の切り口（1文）",
    "targetKeywords": ["キーワード1", "キーワード2"],
    "seasonRelevance": "季節との関連（1文）",
    "priority": "high or medium",
    "reason": "このテーマを選んだ理由（1文）"
  }
]`;

  console.log("[article-researcher] Claude API 呼び出し中...");

  const response = await anthropic.messages.create({
    model: process.env.ARTICLE_WRITER_MODEL || "claude-sonnet-4-6",
    max_tokens: 2000,
    messages: [{ role: "user", content: userPrompt }],
    system: systemPrompt,
  });

  const text = response.content[0].text.trim();
  let themes;
  try {
    // JSON部分を抽出（```json...```対策）
    const jsonStr = text.replace(/^```json?\s*/, "").replace(/\s*```$/, "");
    themes = JSON.parse(jsonStr);
  } catch (err) {
    console.error(`[article-researcher] JSON パースエラー: ${err.message}`);
    console.error("レスポンス:", text);
    process.exit(1);
  }

  // 重複チェック
  themes = themes.filter((t) => !existingSlugs.includes(t.slug));
  if (themes.length === 0) {
    console.error("[article-researcher] 全テーマが既存記事と重複。中止。");
    process.exit(1);
  }

  // 公開日を付与
  const publishDates = getPublishDates(themes.length);
  const weekLabel = getWeekLabel();

  const plan = {
    week: weekLabel,
    generatedAt: new Date().toISOString(),
    articles: themes.slice(0, opts.count).map((t, i) => ({
      themeId: `theme-${weekLabel}-${String(i + 1).padStart(2, "0")}`,
      ...t,
      scheduledPublishDate: publishDates[i] || publishDates[publishDates.length - 1],
      productCount: 3,
    })),
  };

  console.log("\n[article-researcher] 選定テーマ:");
  for (const a of plan.articles) {
    console.log(`  ${a.scheduledPublishDate} | ${a.title} (${a.categoryId})`);
  }

  if (opts.dryRun) {
    console.log("[DRY RUN] article-weekly-plan.json への書き込みをスキップ");
    console.log(JSON.stringify(plan, null, 2));
  } else {
    writeJson("article-weekly-plan.json", plan);
    console.log("\n[article-researcher] article-weekly-plan.json を保存しました");
  }
}

main().catch((err) => {
  console.error("[article-researcher] エラー:", err.message);
  process.exit(1);
});
