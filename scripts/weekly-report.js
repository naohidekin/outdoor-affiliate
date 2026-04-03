#!/usr/bin/env node

/**
 * 週次レポート自動生成
 * GA4 + Search Console + アフィリエイトクリック数から週次サマリーを生成し、
 * Google Sheetsに書き込み + メール通知（Gmail API）
 *
 * 必要な環境変数:
 *   GA4_PROPERTY_ID       — GA4 プロパティID
 *   INDEXING_CREDENTIALS  — GA4/Search Console 権限を持つサービスアカウントJSON
 *   GOOGLE_CREDENTIALS    — Google Sheets書き込み用サービスアカウントJSON
 *   X_SHEET_ID            — レポート書き込み先スプレッドシートID
 *   REPORT_EMAIL          — レポート送信先メールアドレス（省略可）
 *   SITE_URL              — Search Consoleのサイト URL (デフォルト: https://camp-gear-lab.com)
 *
 * 使い方:
 *   node scripts/weekly-report.js
 *   node scripts/weekly-report.js --days=14  (過去14日)
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

const GA4_PROPERTY_ID = process.env.GA4_PROPERTY_ID;
const SITE_URL = process.env.SITE_URL || "https://camp-gear-lab.com";
const DAYS = parseInt(
  process.argv.find((a) => a.startsWith("--days="))?.split("=")[1] || "7"
);

function formatDate(d) {
  return d.toISOString().slice(0, 10);
}

function getDateRange(daysAgo) {
  const end = new Date();
  end.setDate(end.getDate() - 1); // 昨日まで
  const start = new Date(end.getTime() - (daysAgo - 1) * 24 * 60 * 60 * 1000);
  return { start, end };
}

// ============================================================
// 1. GA4 データ取得
// ============================================================
async function getGA4Stats() {
  const { google } = await import("googleapis");
  const credentials = JSON.parse(
    process.env.INDEXING_CREDENTIALS || process.env.GOOGLE_CREDENTIALS || "{}"
  );
  const auth = new google.auth.GoogleAuth({
    credentials,
    scopes: ["https://www.googleapis.com/auth/analytics.readonly"],
  });

  const analyticsData = google.analyticsdata({ version: "v1beta", auth });
  const { start, end } = getDateRange(DAYS);
  const prevStart = new Date(start.getTime() - DAYS * 24 * 60 * 60 * 1000);
  const prevEnd = new Date(start.getTime() - 24 * 60 * 60 * 1000);

  // 今週 vs 前週の比較
  const res = await analyticsData.properties.runReport({
    property: `properties/${GA4_PROPERTY_ID}`,
    requestBody: {
      dateRanges: [
        { startDate: formatDate(start), endDate: formatDate(end) },
        { startDate: formatDate(prevStart), endDate: formatDate(prevEnd) },
      ],
      metrics: [
        { name: "screenPageViews" },
        { name: "totalUsers" },
        { name: "sessions" },
        { name: "engagedSessions" },
        { name: "averageSessionDuration" },
      ],
    },
  });

  const current = res.data.rows?.[0]?.metricValues || [];
  const previous = res.data.rows?.[1]?.metricValues || [];

  const metrics = {
    pageViews: parseInt(current[0]?.value || "0"),
    users: parseInt(current[1]?.value || "0"),
    sessions: parseInt(current[2]?.value || "0"),
    engagedSessions: parseInt(current[3]?.value || "0"),
    avgDuration: parseFloat(current[4]?.value || "0"),
    prev: {
      pageViews: parseInt(previous[0]?.value || "0"),
      users: parseInt(previous[1]?.value || "0"),
      sessions: parseInt(previous[2]?.value || "0"),
    },
  };

  // ページ別PVランキング
  const topPages = await analyticsData.properties.runReport({
    property: `properties/${GA4_PROPERTY_ID}`,
    requestBody: {
      dateRanges: [
        { startDate: formatDate(start), endDate: formatDate(end) },
      ],
      dimensions: [{ name: "pagePath" }],
      metrics: [
        { name: "screenPageViews" },
        { name: "totalUsers" },
      ],
      dimensionFilter: {
        filter: {
          fieldName: "pagePath",
          stringFilter: { matchType: "BEGINS_WITH", value: "/articles/" },
        },
      },
      orderBys: [{ metric: { metricName: "screenPageViews" }, desc: true }],
      limit: 10,
    },
  });

  const pages = (topPages.data.rows || []).map((row) => ({
    path: row.dimensionValues[0].value,
    pageViews: parseInt(row.metricValues[0].value),
    users: parseInt(row.metricValues[1].value),
  }));

  // 流入元
  const sources = await analyticsData.properties.runReport({
    property: `properties/${GA4_PROPERTY_ID}`,
    requestBody: {
      dateRanges: [
        { startDate: formatDate(start), endDate: formatDate(end) },
      ],
      dimensions: [{ name: "sessionSource" }],
      metrics: [{ name: "sessions" }],
      orderBys: [{ metric: { metricName: "sessions" }, desc: true }],
      limit: 10,
    },
  });

  const trafficSources = (sources.data.rows || []).map((row) => ({
    source: row.dimensionValues[0].value,
    sessions: parseInt(row.metricValues[0].value),
  }));

  return { metrics, pages, trafficSources };
}

// ============================================================
// 2. Search Console データ取得
// ============================================================
async function getSearchConsoleStats() {
  const { google } = await import("googleapis");
  const credentials = JSON.parse(
    process.env.INDEXING_CREDENTIALS || process.env.GOOGLE_CREDENTIALS || "{}"
  );
  const auth = new google.auth.GoogleAuth({
    credentials,
    scopes: ["https://www.googleapis.com/auth/webmasters.readonly"],
  });

  const searchConsole = google.searchconsole({ version: "v1", auth });
  const { start, end } = getDateRange(DAYS);

  try {
    // 検索クエリ上位
    const queryRes = await searchConsole.searchanalytics.query({
      siteUrl: SITE_URL,
      requestBody: {
        startDate: formatDate(start),
        endDate: formatDate(end),
        dimensions: ["query"],
        rowLimit: 15,
        type: "web",
      },
    });

    const queries = (queryRes.data.rows || []).map((row) => ({
      query: row.keys[0],
      clicks: row.clicks,
      impressions: row.impressions,
      ctr: (row.ctr * 100).toFixed(1),
      position: row.position.toFixed(1),
    }));

    // ページ別パフォーマンス
    const pageRes = await searchConsole.searchanalytics.query({
      siteUrl: SITE_URL,
      requestBody: {
        startDate: formatDate(start),
        endDate: formatDate(end),
        dimensions: ["page"],
        rowLimit: 10,
        type: "web",
      },
    });

    const searchPages = (pageRes.data.rows || []).map((row) => ({
      page: row.keys[0].replace(SITE_URL, ""),
      clicks: row.clicks,
      impressions: row.impressions,
      ctr: (row.ctr * 100).toFixed(1),
      position: row.position.toFixed(1),
    }));

    // サイト全体サマリー
    const totalRes = await searchConsole.searchanalytics.query({
      siteUrl: SITE_URL,
      requestBody: {
        startDate: formatDate(start),
        endDate: formatDate(end),
        type: "web",
      },
    });

    const totalRow = totalRes.data.rows?.[0] || {};
    const summary = {
      totalClicks: totalRow.clicks || 0,
      totalImpressions: totalRow.impressions || 0,
      avgCtr: ((totalRow.ctr || 0) * 100).toFixed(1),
      avgPosition: (totalRow.position || 0).toFixed(1),
    };

    return { queries, searchPages, summary };
  } catch (err) {
    console.log(`⚠️ Search Console データ取得失敗: ${err.message}`);
    return { queries: [], searchPages: [], summary: null };
  }
}

// ============================================================
// 3. アフィリエイトクリック集計
// ============================================================
function getAffiliateClicks() {
  const clicksFile = path.join(DATA_DIR, "affiliate-clicks.json");
  if (!fs.existsSync(clicksFile)) return { total: 0, byStore: {}, topProducts: [] };

  const clicks = JSON.parse(fs.readFileSync(clicksFile, "utf-8"));
  const { start } = getDateRange(DAYS);
  const startStr = formatDate(start);

  const weekClicks = clicks.filter((c) => c.timestamp >= startStr);

  const byStore = {};
  const byProduct = {};
  for (const c of weekClicks) {
    byStore[c.store] = (byStore[c.store] || 0) + 1;
    const key = `${c.productId} (${c.store})`;
    byProduct[key] = (byProduct[key] || 0) + 1;
  }

  const topProducts = Object.entries(byProduct)
    .sort((a, b) => b[1] - a[1])
    .slice(0, 10)
    .map(([name, count]) => ({ name, count }));

  return { total: weekClicks.length, byStore, topProducts };
}

// ============================================================
// 4. レポート生成
// ============================================================
function generateReport(ga4, gsc, clicks, dateRange) {
  const pctChange = (curr, prev) => {
    if (prev === 0) return curr > 0 ? "+∞" : "±0";
    const pct = ((curr - prev) / prev * 100).toFixed(1);
    return pct > 0 ? `+${pct}%` : `${pct}%`;
  };

  const arrow = (curr, prev) => curr > prev ? "📈" : curr < prev ? "📉" : "➡️";

  let report = "";
  report += `━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n`;
  report += `📊 週次レポート（${formatDate(dateRange.start)} 〜 ${formatDate(dateRange.end)}）\n`;
  report += `━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n`;

  // GA4 サマリー
  report += `🔹 サイト全体\n`;
  report += `  PV: ${ga4.metrics.pageViews.toLocaleString()} ${arrow(ga4.metrics.pageViews, ga4.metrics.prev.pageViews)} (前週比 ${pctChange(ga4.metrics.pageViews, ga4.metrics.prev.pageViews)})\n`;
  report += `  ユーザー: ${ga4.metrics.users.toLocaleString()} ${arrow(ga4.metrics.users, ga4.metrics.prev.users)} (前週比 ${pctChange(ga4.metrics.users, ga4.metrics.prev.users)})\n`;
  report += `  セッション: ${ga4.metrics.sessions.toLocaleString()} ${arrow(ga4.metrics.sessions, ga4.metrics.prev.sessions)} (前週比 ${pctChange(ga4.metrics.sessions, ga4.metrics.prev.sessions)})\n`;
  report += `  エンゲージメント率: ${ga4.metrics.sessions > 0 ? (ga4.metrics.engagedSessions / ga4.metrics.sessions * 100).toFixed(1) : 0}%\n`;
  report += `  平均セッション時間: ${Math.floor(ga4.metrics.avgDuration / 60)}分${Math.floor(ga4.metrics.avgDuration % 60)}秒\n\n`;

  // 人気ページ
  if (ga4.pages.length > 0) {
    report += `🔹 人気記事 TOP${Math.min(ga4.pages.length, 10)}\n`;
    ga4.pages.forEach((p, i) => {
      const slug = p.path.replace("/articles/", "").replace(/\/$/, "");
      report += `  ${i + 1}. ${slug} — ${p.pageViews} PV (${p.users} UU)\n`;
    });
    report += `\n`;
  }

  // 流入元
  if (ga4.trafficSources.length > 0) {
    report += `🔹 流入元\n`;
    ga4.trafficSources.forEach((s) => {
      report += `  ${s.source || "(direct)"}: ${s.sessions} セッション\n`;
    });
    report += `\n`;
  }

  // Search Console
  if (gsc.summary) {
    report += `🔹 Google 検索パフォーマンス\n`;
    report += `  検索クリック: ${gsc.summary.totalClicks.toLocaleString()}\n`;
    report += `  表示回数: ${gsc.summary.totalImpressions.toLocaleString()}\n`;
    report += `  平均CTR: ${gsc.summary.avgCtr}%\n`;
    report += `  平均掲載順位: ${gsc.summary.avgPosition}\n\n`;
  }

  if (gsc.queries.length > 0) {
    report += `🔹 検索クエリ TOP${Math.min(gsc.queries.length, 15)}\n`;
    gsc.queries.forEach((q, i) => {
      report += `  ${i + 1}. "${q.query}" — ${q.clicks}クリック / ${q.impressions}表示 / CTR ${q.ctr}% / 順位 ${q.position}\n`;
    });
    report += `\n`;
  }

  // アフィリエイトクリック
  report += `🔹 アフィリエイトクリック\n`;
  report += `  合計: ${clicks.total}クリック\n`;
  if (Object.keys(clicks.byStore).length > 0) {
    for (const [store, count] of Object.entries(clicks.byStore)) {
      report += `    ${store}: ${count}\n`;
    }
  }
  if (clicks.topProducts.length > 0) {
    report += `  商品別 TOP:\n`;
    clicks.topProducts.forEach((p) => {
      report += `    ${p.name}: ${p.count}クリック\n`;
    });
  }
  report += `\n`;

  // 改善ポイント
  report += `🔹 改善ポイント\n`;
  if (gsc.queries.length > 0) {
    const highImpLowCtr = gsc.queries
      .filter((q) => q.impressions > 50 && parseFloat(q.ctr) < 3)
      .slice(0, 3);
    if (highImpLowCtr.length > 0) {
      report += `  ⚠️ 表示多・CTR低（タイトル/メタ改善候補）:\n`;
      highImpLowCtr.forEach((q) => {
        report += `    "${q.query}" — ${q.impressions}表示, CTR ${q.ctr}%\n`;
      });
    }
    const rankUp = gsc.queries
      .filter((q) => parseFloat(q.position) >= 5 && parseFloat(q.position) <= 15)
      .slice(0, 3);
    if (rankUp.length > 0) {
      report += `  🎯 順位改善の余地あり（5〜15位）:\n`;
      rankUp.forEach((q) => {
        report += `    "${q.query}" — 順位 ${q.position}, ${q.clicks}クリック\n`;
      });
    }
  }

  return report;
}

// ============================================================
// 5. Sheets に保存
// ============================================================
async function saveToSheets(report, ga4, gsc, clicks, dateRange) {
  const { google } = await import("googleapis");
  const credentials = JSON.parse(process.env.GOOGLE_CREDENTIALS || "{}");
  const auth = new google.auth.GoogleAuth({
    credentials,
    scopes: ["https://www.googleapis.com/auth/spreadsheets"],
  });

  const sheets = google.sheets({ version: "v4", auth });
  const spreadsheetId = process.env.X_SHEET_ID;
  if (!spreadsheetId) {
    console.log("⚠️ X_SHEET_ID未設定。Sheets保存をスキップ");
    return;
  }

  // 週次レポートシートに追加
  const sheetName = "週次レポート";

  // シートの存在確認・作成
  try {
    const spreadsheet = await sheets.spreadsheets.get({ spreadsheetId });
    const exists = spreadsheet.data.sheets.some(
      (s) => s.properties.title === sheetName
    );
    if (!exists) {
      await sheets.spreadsheets.batchUpdate({
        spreadsheetId,
        requestBody: {
          requests: [{ addSheet: { properties: { title: sheetName } } }],
        },
      });
      // ヘッダー追加
      await sheets.spreadsheets.values.update({
        spreadsheetId,
        range: `${sheetName}!A1:J1`,
        valueInputOption: "RAW",
        requestBody: {
          values: [["期間", "PV", "PV前週比", "UU", "セッション", "検索クリック", "表示回数", "平均順位", "アフィクリック", "生成日時"]],
        },
      });
    }
  } catch {
    // シート操作エラーは無視
  }

  const row = [
    `${formatDate(dateRange.start)}〜${formatDate(dateRange.end)}`,
    ga4.metrics.pageViews,
    ga4.metrics.prev.pageViews > 0
      ? `${((ga4.metrics.pageViews - ga4.metrics.prev.pageViews) / ga4.metrics.prev.pageViews * 100).toFixed(1)}%`
      : "-",
    ga4.metrics.users,
    ga4.metrics.sessions,
    gsc.summary?.totalClicks || 0,
    gsc.summary?.totalImpressions || 0,
    gsc.summary?.avgPosition || "-",
    clicks.total,
    new Date().toISOString(),
  ];

  await sheets.spreadsheets.values.append({
    spreadsheetId,
    range: `${sheetName}!A:J`,
    valueInputOption: "RAW",
    requestBody: { values: [row] },
  });

  console.log("✅ Google Sheetsに保存しました");
}

// ============================================================
// 6. メール送信（Gmail API or SMTP不要 — Sheetsトリガーで代用）
// ============================================================
async function sendEmailNotification(report) {
  const email = process.env.REPORT_EMAIL;
  if (!email) {
    console.log("ℹ️ REPORT_EMAIL未設定。メール通知をスキップ");
    return;
  }

  // Google Sheets APIでメール通知は直接できないので、
  // レポートファイルを保存してGAS/IFTTTで通知する方式
  const reportFile = path.join(DATA_DIR, "latest-weekly-report.txt");
  fs.writeFileSync(reportFile, report, "utf-8");
  console.log(`📄 レポートファイル保存: ${reportFile}`);
  console.log(`ℹ️ メール通知は Google Apps Script または IFTTT で設定してください`);
}

// ============================================================
// メイン
// ============================================================
async function main() {
  if (!GA4_PROPERTY_ID) {
    console.log("⚠️ GA4_PROPERTY_ID が未設定です。.env.local を確認してください。");
    process.exit(0);
  }

  const dateRange = getDateRange(DAYS);
  console.log(`\n📊 週次レポート生成`);
  console.log(`  期間: ${formatDate(dateRange.start)} 〜 ${formatDate(dateRange.end)}\n`);

  // 並列でデータ取得
  console.log("🔍 データ取得中...");
  const [ga4, gsc] = await Promise.all([
    getGA4Stats(),
    getSearchConsoleStats(),
  ]);
  const clicks = getAffiliateClicks();

  console.log("  ✅ GA4 データ取得完了");
  console.log(`  ${gsc.summary ? "✅" : "⚠️"} Search Console データ取得${gsc.summary ? "完了" : "失敗（権限未設定の可能性）"}`);
  console.log(`  ✅ アフィリエイトクリック集計完了 (${clicks.total}件)\n`);

  // レポート生成
  const report = generateReport(ga4, gsc, clicks, dateRange);
  console.log(report);

  // 保存
  const reportFile = path.join(DATA_DIR, "latest-weekly-report.txt");
  fs.writeFileSync(reportFile, report, "utf-8");
  console.log(`📄 レポート保存: ${reportFile}`);

  // Sheets保存
  await saveToSheets(report, ga4, gsc, clicks, dateRange);

  // メール通知
  await sendEmailNotification(report);

  console.log("\n✅ 週次レポート生成完了");
}

main().catch((err) => {
  console.error("エラー:", err.message);
  process.exit(1);
});
