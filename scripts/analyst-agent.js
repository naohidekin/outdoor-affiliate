#!/usr/bin/env node

/**
 * Analyst Agent — パフォーマンス分析・Writer へのフィードバック生成
 *
 * GA4 + Sheets のデータから投稿パフォーマンスを分析し、
 * analyst-feedback.json を通じて Writer Agent にフィードバックを渡す。
 *
 * 使い方:
 *   node scripts/analyst-agent.js                      # 28日分析、feedback更新
 *   node scripts/analyst-agent.js --dry-run            # 表示のみ（書き込みなし）
 *   node scripts/analyst-agent.js --days 7             # 分析期間指定
 */

import { google } from "googleapis";
import {
  loadEnv,
  readJson,
  writeJson,
  checkKillSwitch,
  loadPostHistory,
} from "../src/lib/x-agent-utils.mjs";

loadEnv();

const DRAFT_SHEET = "下書き管理";

// ─── CLI ─────────────────────────────────────────────

function parseArgs() {
  const args = process.argv.slice(2);
  const opts = { dryRun: false, days: 28 };
  for (let i = 0; i < args.length; i++) {
    switch (args[i]) {
      case "--dry-run":
        opts.dryRun = true;
        break;
      case "--days":
        opts.days = parseInt(args[++i], 10) || 28;
        break;
    }
  }
  return opts;
}

// ─── GA4 からX経由トラフィック取得 ────────────────────

async function getXTrafficFromGA4(days) {
  const propertyId = process.env.GA4_PROPERTY_ID;
  if (!propertyId) {
    console.warn("[analyst] GA4_PROPERTY_ID 未設定。GA4データなしで続行します。");
    return null;
  }

  try {
    const credentials = JSON.parse(
      process.env.INDEXING_CREDENTIALS || process.env.GOOGLE_CREDENTIALS || "{}"
    );
    const auth = new google.auth.GoogleAuth({
      credentials,
      scopes: ["https://www.googleapis.com/auth/analytics.readonly"],
    });

    const analyticsData = google.analyticsdata({ version: "v1beta", auth });
    const today = new Date();
    const startDate = new Date(today.getTime() - days * 24 * 60 * 60 * 1000);
    const formatDate = (d) => d.toISOString().slice(0, 10);

    // X経由（utm_source=x）のページ別PV
    const res = await analyticsData.properties.runReport({
      property: `properties/${propertyId}`,
      requestBody: {
        dateRanges: [
          { startDate: formatDate(startDate), endDate: formatDate(today) },
        ],
        dimensions: [{ name: "pagePath" }],
        metrics: [
          { name: "screenPageViews" },
          { name: "sessions" },
        ],
        dimensionFilter: {
          andGroup: {
            expressions: [
              {
                filter: {
                  fieldName: "sessionSource",
                  stringFilter: { matchType: "EXACT", value: "x" },
                },
              },
              {
                filter: {
                  fieldName: "pagePath",
                  stringFilter: { matchType: "BEGINS_WITH", value: "/articles/" },
                },
              },
            ],
          },
        },
        orderBys: [
          { metric: { metricName: "screenPageViews" }, desc: true },
        ],
        limit: 50,
      },
    });

    const rows = res.data.rows || [];
    return rows.map((row) => ({
      slug: row.dimensionValues[0].value.replace("/articles/", "").replace(/\/$/, ""),
      pageViews: parseInt(row.metricValues[0].value),
      sessions: parseInt(row.metricValues[1].value),
    }));
  } catch (err) {
    console.warn(`[analyst] GA4取得エラー（スキップ）: ${err.message}`);
    return null;
  }
}

// ─── Sheets から投稿履歴取得 ──────────────────────────

async function getPostsFromSheets(days) {
  try {
    const credentials = JSON.parse(process.env.GOOGLE_CREDENTIALS || "{}");
    const auth = new google.auth.GoogleAuth({
      credentials,
      scopes: ["https://www.googleapis.com/auth/spreadsheets.readonly"],
    });
    const sheets = google.sheets({ version: "v4", auth });
    const spreadsheetId = process.env.X_SHEET_ID;

    if (!spreadsheetId) {
      console.warn("[analyst] X_SHEET_ID 未設定");
      return [];
    }

    const res = await sheets.spreadsheets.values.get({
      spreadsheetId,
      range: `${DRAFT_SHEET}!A2:R`,
    });

    const rows = res.data.values || [];
    const cutoff = new Date();
    cutoff.setDate(cutoff.getDate() - days);

    return rows
      .filter((r) => r[0] && r[8]) // id と generatedAt が存在
      .map((r) => ({
        id: r[0],
        type: r[1],
        text: r[2],
        articleSlug: r[3] || null,
        status: r[6],
        generatedAt: r[8],
        axis: r[10] || null,
        validationErrors: r[12] || "",
        autoApproved: r[13] || "",
        selfScore: r[14] ? parseFloat(r[14]) : null,
        firstLinePattern: r[15] || null,
      }))
      .filter((p) => new Date(p.generatedAt) >= cutoff);
  } catch (err) {
    console.warn(`[analyst] Sheets取得エラー: ${err.message}`);
    return [];
  }
}

// ─── パフォーマンス分析 ──────────────────────────────

function analyzePerformance(posts, ga4Data) {
  const now = new Date();
  const periodStart = new Date(now);
  periodStart.setDate(periodStart.getDate() - 28);

  // タイプ別統計
  const typeStats = {};
  for (const p of posts) {
    if (!typeStats[p.type]) {
      typeStats[p.type] = { total: 0, approved: 0, ngFailed: 0, scores: [] };
    }
    const s = typeStats[p.type];
    s.total++;
    if (p.status === "approved" || p.status === "posted" || p.status === "queued") {
      s.approved++;
    }
    if (p.validationErrors && p.validationErrors.trim()) {
      s.ngFailed++;
    }
    if (p.selfScore != null) {
      s.scores.push(p.selfScore);
    }
  }

  // 高パフォーマンスタイプ: approved率が高い + NG失敗が少ない
  const topPerformingTypes = [];
  const lowPerformingTypes = [];

  for (const [type, s] of Object.entries(typeStats)) {
    const approvedRate = s.total > 0 ? s.approved / s.total : 0;
    const ngRate = s.total > 0 ? s.ngFailed / s.total : 0;
    const avgScore = s.scores.length > 0
      ? s.scores.reduce((a, b) => a + b, 0) / s.scores.length
      : null;

    if (approvedRate > 0.7 && ngRate < 0.1) {
      topPerformingTypes.push(type);
    }
    if (ngRate > 0.2) {
      lowPerformingTypes.push(type);
    }
  }

  // パターン分析（post-history.json ベース）
  const history = loadPostHistory();
  const effectivePatterns = [];
  const avoidPatterns = [];

  // 高スコア投稿のパターン
  const scoredEntries = history.entries.filter((e) => e.selfScore != null);
  const patternScores = {};
  for (const e of scoredEntries) {
    const p = e.firstLinePattern;
    if (!p) continue;
    if (!patternScores[p]) patternScores[p] = { scores: [], count: 0 };
    patternScores[p].scores.push(e.selfScore);
    patternScores[p].count++;
  }

  for (const [pattern, data] of Object.entries(patternScores)) {
    const avg = data.scores.reduce((a, b) => a + b, 0) / data.scores.length;
    if (avg >= 7.5 && data.count >= 2) {
      effectivePatterns.push({
        pattern,
        reason: `平均スコア ${avg.toFixed(1)}（${data.count}件）`,
      });
    }
  }

  // NG頻出表現
  const ngWords = {};
  for (const p of posts) {
    if (p.validationErrors) {
      for (const err of p.validationErrors.split(" / ")) {
        const trimmed = err.trim();
        if (trimmed) {
          ngWords[trimmed] = (ngWords[trimmed] || 0) + 1;
        }
      }
    }
  }
  for (const [word, count] of Object.entries(ngWords)) {
    if (count >= 2) {
      avoidPatterns.push({ pattern: word, reason: `NG検出 ${count}回` });
    }
  }

  // 軸別フィードバック
  const axisFeedback = {};
  const axisGroups = {};
  for (const p of posts) {
    const a = p.axis || "unknown";
    if (!axisGroups[a]) axisGroups[a] = { total: 0, ng: 0, approved: 0 };
    axisGroups[a].total++;
    if (p.validationErrors && p.validationErrors.trim()) axisGroups[a].ng++;
    if (["approved", "posted", "queued"].includes(p.status)) axisGroups[a].approved++;
  }
  for (const [axis, g] of Object.entries(axisGroups)) {
    const approvedRate = g.total > 0 ? ((g.approved / g.total) * 100).toFixed(0) : 0;
    const ngRate = g.total > 0 ? ((g.ng / g.total) * 100).toFixed(0) : 0;
    axisFeedback[axis] = `${g.total}件生成、承認率${approvedRate}%、NG率${ngRate}%`;
  }

  // GA4 連携情報
  let seasonalInsight = "";
  if (ga4Data && ga4Data.length > 0) {
    const topSlug = ga4Data[0];
    seasonalInsight = `X経由PVトップ: ${topSlug.slug} (${topSlug.pageViews}PV)`;
  }

  // Writer 向けヒント
  const writerHints = [];
  if (effectivePatterns.length > 0) {
    writerHints.push(`高スコアパターン: ${effectivePatterns.map((p) => p.pattern).join(", ")}`);
  }
  if (lowPerformingTypes.length > 0) {
    writerHints.push(`NG率が高いタイプ: ${lowPerformingTypes.join(", ")} — 表現を見直す`);
  }
  if (ga4Data && ga4Data.length > 0) {
    writerHints.push(`X経由PVが高い記事を article_promo で優先的に紹介する`);
  }

  const month = now.getMonth() + 1;
  const seasonHints = {
    1: "冬キャンプ・防寒ネタが刺さる", 2: "春キャンプ準備が始まる",
    3: "花見キャンプ・新生活デビュー", 4: "GW準備ネタが刺さる。寒暖差ネタも反応良い",
    5: "GWキャンプ・虫対策", 6: "梅雨・雨キャンプ対策",
    7: "夏キャンプ・暑さ対策", 8: "高原キャンプ・川遊び",
    9: "秋キャンプ開始・焚き火", 10: "紅葉キャンプ・焚き火料理",
    11: "冬準備・防寒ギア", 12: "年末キャンプ・冬装備",
  };
  if (!seasonalInsight) {
    seasonalInsight = seasonHints[month] || "";
  }

  return {
    version: 1,
    updatedAt: now.toISOString(),
    period: `${periodStart.toISOString().slice(0, 10)} ~ ${now.toISOString().slice(0, 10)}`,
    topPerformingTypes,
    lowPerformingTypes,
    effectivePatterns,
    avoidPatterns,
    axisFeedback,
    seasonalInsight,
    writerHints,
  };
}

// ─── メイン ──────────────────────────────────────────

async function main() {
  const opts = parseArgs();

  // Kill switch チェック
  const ks = checkKillSwitch();
  if (ks.killed) {
    console.error(`[analyst] KILL SWITCH 有効: ${ks.reason}`);
    process.exit(1);
  }

  console.log(`[analyst] 分析開始 (過去${opts.days}日)`);

  // データ収集（並行）
  const [ga4Data, sheetsPosts] = await Promise.all([
    getXTrafficFromGA4(opts.days),
    getPostsFromSheets(opts.days),
  ]);

  console.log(`[analyst] Sheets投稿: ${sheetsPosts.length}件`);
  if (ga4Data) {
    console.log(`[analyst] GA4 X経由ページ: ${ga4Data.length}件`);
  }

  // 分析実行
  const feedback = analyzePerformance(sheetsPosts, ga4Data);

  // 結果表示
  console.log("\n[analyst] フィードバックサマリ:");
  console.log(`  高パフォーマンスタイプ: ${feedback.topPerformingTypes.join(", ") || "なし"}`);
  console.log(`  低パフォーマンスタイプ: ${feedback.lowPerformingTypes.join(", ") || "なし"}`);
  console.log(`  有効パターン: ${feedback.effectivePatterns.length}件`);
  console.log(`  回避パターン: ${feedback.avoidPatterns.length}件`);
  console.log(`  季節インサイト: ${feedback.seasonalInsight}`);
  if (feedback.writerHints.length > 0) {
    console.log("  Writerヒント:");
    for (const h of feedback.writerHints) console.log(`    - ${h}`);
  }

  // 書き込み
  if (opts.dryRun) {
    console.log("\n[DRY RUN] analyst-feedback.json の書き込みをスキップしました");
    console.log(JSON.stringify(feedback, null, 2));
  } else {
    writeJson("analyst-feedback.json", feedback);
    console.log("\n[analyst] analyst-feedback.json を更新しました");
  }
}

main().catch((err) => {
  console.error("[analyst] エラー:", err.message);
  process.exit(1);
});
