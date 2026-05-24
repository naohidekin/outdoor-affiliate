#!/usr/bin/env node

/**
 * Supervisor Agent — 全体監視・KILL SWITCH 制御・異常検知・バックアップ
 *
 * 使い方:
 *   node scripts/supervisor-agent.js --check           # 異常チェック (exit 0=正常, 1=KILL有効)
 *   node scripts/supervisor-agent.js --kill "理由"     # KILL SWITCH 有効化
 *   node scripts/supervisor-agent.js --resume          # KILL SWITCH 解除
 *   node scripts/supervisor-agent.js --backup          # Sheets バックアップ
 *   node scripts/supervisor-agent.js --quality-check   # selfScore 品質チェック
 */

import { google } from "googleapis";
import fs from "fs";
import path from "path";
import { fileURLToPath } from "url";
import {
  loadEnv,
  readJson,
  writeJson,
  checkKillSwitch,
  loadPostHistory,
} from "../src/lib/x-agent-utils.mjs";

loadEnv();

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const DATA_DIR = path.join(__dirname, "..", "data");
const DRAFT_SHEET = "下書き管理";

function jstDateString(d = new Date()) {
  return new Date(d.getTime() + 9 * 60 * 60 * 1000).toISOString().slice(0, 10);
}

function jstIsoString(d = new Date()) {
  const shifted = new Date(d.getTime() + 9 * 60 * 60 * 1000);
  return `${shifted.toISOString().slice(0, 19)}+09:00`;
}

// ─── CLI パーサ ──────────────────────────────────────

function parseArgs() {
  const args = process.argv.slice(2);
  const opts = { action: null, reason: "", cycle: 1, articleId: null };
  for (let i = 0; i < args.length; i++) {
    switch (args[i]) {
      case "--check":
        opts.action = "check";
        break;
      case "--kill":
        opts.action = "kill";
        opts.reason = args[++i] || "手動停止";
        break;
      case "--resume":
        opts.action = "resume";
        break;
      case "--backup":
        opts.action = "backup";
        break;
      case "--quality-check":
        opts.action = "quality-check";
        break;
      case "--weekly-report":
        opts.action = "weekly-report";
        break;
      case "--evaluate-article":
        opts.action = "evaluate-article";
        opts.articleId = args[++i];
        break;
      case "--cycle":
        opts.cycle = Number(args[++i] || 1);
        break;
    }
  }
  return opts;
}

const WISE_PASS_THRESHOLD = 7.5;
const WISE_CRITERIA = [
  "wise_w", "wise_i", "wise_s", "wise_e", "wise_ai",
  "affiliate_links", "comparison_table", "internal_links", "faq", "word_count",
];

function appendRejected(record) {
  const rejected = readJson("rejected.json") || [];
  rejected.push(record);
  writeJson("rejected.json", rejected);
}

function scoreWiseArticle(article, topic) {
  const content = article.content || "";
  const wordCount = content.length;
  const faqCount = Array.isArray(article.faqs) ? article.faqs.length : 0;
  const linkCount = (content.match(/\[[^\]]+\]\(\/articles\/[^)]+\)/g) || []).length;
  const hasComparisonTag = /\{\{comparison:[^}]+\}\}/.test(content);
  const hasAmazon = /amazon\./i.test(content);
  const hasRakuten = /rakuten\./i.test(content);
  const banned = [
    "することができます", "と言えるでしょう", "という点で優れています", "ぜひ参考にしてみてください",
    "まとめると", "総合的に判断すると", "非常に重要です", "詳しく解説します",
    "しっかりと確認しましょう", "という選択肢もあります", "といった特徴があります",
  ];
  const bannedHits = banned.filter((p) => content.includes(p)).length;
  const wise = article.wise_scores || {};
  const wf = topic?.format_recommendation || "guide";
  const minMax = {
    ranking: [5000, 8000], comparison: [5000, 8000],
    guide: [3000, 5000], "how-to": [3000, 5000], review: [2000, 3500],
  }[wf] || [3000, 5000];

  const criterionScores = {
    wise_w: Math.max(1, Math.min(10, Math.round(((wise.w || 3) / 5) * 10))),
    wise_i: Math.max(1, Math.min(10, Math.round(((wise.i || 3) / 5) * 10))),
    wise_s: Math.max(1, Math.min(10, Math.round(((wise.s || 3) / 5) * 10))),
    wise_e: Math.max(1, Math.min(10, Math.round(((wise.e || 3) / 5) * 10))),
    wise_ai: Math.max(1, Math.min(10, Math.round(((wise.ai || 3) / 5) * 10))),
    affiliate_links: hasAmazon && hasRakuten ? 10 : (hasAmazon || hasRakuten ? 6 : 2),
    comparison_table: hasComparisonTag ? 10 : 2,
    internal_links: linkCount >= 2 && linkCount <= 3 ? 10 : (linkCount >= 1 ? 6 : 2),
    faq: faqCount >= 3 && faqCount <= 5 ? 10 : (faqCount >= 2 ? 6 : 2),
    word_count: wordCount >= minMax[0] && wordCount <= minMax[1] ? 10 : (wordCount >= 2000 && wordCount <= 8000 ? 6 : 2),
  };

  const average = WISE_CRITERIA.reduce((s, k) => s + criterionScores[k], 0) / 10;
  const score = Number(average.toFixed(2));
  const passed = score >= WISE_PASS_THRESHOLD;
  const feedback = WISE_CRITERIA
    .filter((k) => criterionScores[k] < 8)
    .map((k) => `${k} が不足 (${criterionScores[k]}/10)`);
  if (bannedHits > 0) feedback.push(`禁止フレーズ検出 ${bannedHits}件`);

  return { passed, score, criterionScores, feedback };
}

function evaluateArticle(articleId, cycle = 1) {
  const articles = readJson("articles.json") || [];
  const plan = readJson("article-weekly-plan.json") || {};
  const article = articles.find((a) => a.id === articleId);
  const topic = (plan.articles || []).find((t) => t.slug === article?.slug);
  if (!article) {
    console.log(JSON.stringify({ passed: false, score: 0, feedback: ["article not found"] }));
    return;
  }
  const result = scoreWiseArticle(article, topic);
  if (!result.passed && Number(cycle) >= 2) {
    appendRejected({
      id: article.id,
      slug: article.slug,
      title: article.title,
      cycle: Number(cycle),
      score: result.score,
      feedback: result.feedback,
      rejectedAt: jstIsoString(),
    });
  }
  console.log(JSON.stringify(result));
}

// ─── Sheets 接続 ─────────────────────────────────────

function getSheets() {
  const credentials = JSON.parse(process.env.GOOGLE_CREDENTIALS);
  const auth = new google.auth.GoogleAuth({
    credentials,
    scopes: ["https://www.googleapis.com/auth/spreadsheets.readonly"],
  });
  return google.sheets({ version: "v4", auth });
}

// ─── KILL SWITCH ────────────────────────────────────

function enableKillSwitch(reason, triggeredBy = "manual") {
  const existing = readJson("kill-switch.json") || {};
  writeJson("kill-switch.json", {
    ...existing,
    enabled: true,
    reason,
    enabledAt: jstIsoString(),
    enabledBy: triggeredBy,
  });
  console.log(`[supervisor] KILL SWITCH 有効化 (by ${triggeredBy}): ${reason}`);
}

/**
 * 連続エラーカウントを記録・取得。3連続で自動KILL。
 */
function recordError(errorType) {
  const ks = readJson("kill-switch.json") || {};
  const errors = ks.consecutiveErrors || [];
  errors.push({ type: errorType, at: jstIsoString() });

  // 直近3件のみ保持
  const recent = errors.slice(-3);
  ks.consecutiveErrors = recent;
  writeJson("kill-switch.json", ks);

  // 3連続エラーで自動KILL
  if (recent.length >= 3) {
    enableKillSwitch(
      `連続エラー3回検知: ${recent.map((e) => e.type).join(", ")}`,
      "auto-supervisor"
    );
    return true; // killed
  }
  return false;
}

function clearErrorCount() {
  const ks = readJson("kill-switch.json") || {};
  if (ks.consecutiveErrors?.length > 0) {
    ks.consecutiveErrors = [];
    writeJson("kill-switch.json", ks);
  }
}

function disableKillSwitch() {
  const existing = readJson("kill-switch.json") || {};
  writeJson("kill-switch.json", {
    ...existing,
    enabled: false,
    reason: "",
    enabledAt: null,
    enabledBy: "manual",
  });
  console.log("[supervisor] KILL SWITCH 解除");
}

// ─── 異常チェック ────────────────────────────────────

async function runAnomalyCheck() {
  const warnings = [];

  // 1. KILL SWITCH 確認
  const ks = checkKillSwitch();
  if (ks.killed) {
    console.log(`[supervisor] KILL SWITCH 有効: ${ks.reason}`);
    process.exit(1);
  }

  // 1.5. 記事パイプライン Kill Switch 確認
  const ksData = readJson("kill-switch.json");
  if (ksData?.articleEnabled) {
    console.log("[supervisor] 記事パイプライン Kill Switch 有効");
  }

  // 2. 投稿履歴チェック
  const history = loadPostHistory();
  if (history.entries.length > 0) {
    // selfScore < 5.0 が3連続チェック
    const scores = history.entries.slice(-10).map((e) => e.selfScore).filter(Boolean);
    let consecutive = 0;
    for (const s of scores) {
      if (s < 5.0) {
        consecutive++;
        if (consecutive >= 3) {
          warnings.push(`selfScore < 5.0 が3件連続 (直近スコア: ${scores.slice(-5).join(", ")})`);
          break;
        }
      } else {
        consecutive = 0;
      }
    }
  }

  // 3. Sheets ベースチェック（scheduledDate 超過）
  try {
    const sheets = getSheets();
    const res = await sheets.spreadsheets.values.get({
      spreadsheetId: process.env.X_SHEET_ID,
      range: `${DRAFT_SHEET}!A2:N`,
    });
    const rows = res.data.values || [];
    const today = jstDateString();

    // scheduledDate < today かつ status != posted の件数
    let overdueCount = 0;
    let ngFailCount = 0;
    let totalCount = 0;

    for (const r of rows) {
      if (!r[0]) continue;
      totalCount++;
      const status = r[6];
      const scheduledDate = r[7];
      const validationErrors = r[12];

      if (scheduledDate && scheduledDate < today && status !== "posted" && status !== "discarded") {
        overdueCount++;
      }
      if (validationErrors && validationErrors.trim()) {
        ngFailCount++;
      }
    }

    if (overdueCount >= 3) {
      warnings.push(`スケジュール超過投稿: ${overdueCount}件`);
    }

    // NG失敗率 > 30%
    if (totalCount > 0 && ngFailCount / totalCount > 0.3) {
      warnings.push(`NGチェック失敗率: ${((ngFailCount / totalCount) * 100).toFixed(1)}% (${ngFailCount}/${totalCount})`);
    }
  } catch (err) {
    console.warn(`[supervisor] Sheets取得エラー（スキップ）: ${err.message}`);
  }

  // 結果出力
  if (warnings.length > 0) {
    console.log(`[supervisor] 警告 ${warnings.length}件:`);
    for (const w of warnings) console.log(`  - ${w}`);
    // 警告があってもパイプラインは継続（exit 0）
    // ただし深刻な異常はexit 1でパイプラインを停止
    const hasCritical = warnings.some(
      (w) => w.includes("selfScore < 5.0 が3件連続") || w.includes("NGチェック失敗率")
    );
    if (hasCritical) {
      // 連続エラーとして記録。3回連続で自動KILL
      const killed = recordError(warnings.find((w) => w.includes("selfScore") || w.includes("NG")) || "critical");
      if (killed) {
        console.error("[supervisor] 連続エラー3回。自動KILL SWITCH を有効化しました。");
        process.exit(1);
      }
      console.error("[supervisor] 深刻な異常を検知。パイプラインを停止します。");
      process.exit(1);
    }
  } else {
    console.log("[supervisor] 異常なし");
    // 正常時はエラーカウントをリセット
    clearErrorCount();
  }

  process.exit(0);
}

// ─── バックアップ ────────────────────────────────────

async function runBackup() {
  const backupDir = path.join(DATA_DIR, "backups");
  if (!fs.existsSync(backupDir)) {
    fs.mkdirSync(backupDir, { recursive: true });
  }

  try {
    const sheets = getSheets();
    const spreadsheetId = process.env.X_SHEET_ID;

    // 下書き管理シートの全データ取得
    const draftRes = await sheets.spreadsheets.values.get({
      spreadsheetId,
      range: `${DRAFT_SHEET}!A:R`,
    });

    // X投稿管理シートの全データ取得
    let postRes = { data: { values: [] } };
    try {
      postRes = await sheets.spreadsheets.values.get({
        spreadsheetId,
        range: "X投稿管理!A:H",
      });
    } catch {
      console.warn("[supervisor] X投稿管理シートが見つかりません（スキップ）");
    }

    const timestamp = new Date()
      .toISOString()
      .replace(/[:-]/g, "")
      .replace("T", "-")
      .split(".")[0];

    // ローカルJSONのバックアップ
    const localFiles = {};
    for (const f of ["articles.json", "products.json"]) {
      const data = readJson(f);
      if (data) localFiles[f] = data;
    }

    const backup = {
      createdAt: jstIsoString(),
      sheets: {
        "下書き管理": draftRes.data.values || [],
        "X投稿管理": postRes.data.values || [],
      },
      localFiles,
    };

    const backupPath = path.join(backupDir, `sheets-${timestamp}.json`);
    fs.writeFileSync(backupPath, JSON.stringify(backup, null, 2), "utf-8");
    console.log(`[supervisor] バックアップ完了: ${path.basename(backupPath)}`);
  } catch (err) {
    console.error(`[supervisor] バックアップ失敗: ${err.message}`);
    process.exit(1);
  }
}

// ─── 品質チェック ────────────────────────────────────

function runQualityCheck() {
  const history = loadPostHistory();
  const entries = history.entries.filter((e) => e.selfScore != null);

  if (entries.length === 0) {
    console.log("[supervisor] 採点済み投稿がありません");
    return;
  }

  const recent = entries.slice(-20);
  const avgScore = recent.reduce((sum, e) => sum + e.selfScore, 0) / recent.length;

  // 低スコア連続チェック
  let maxConsecutiveLow = 0;
  let currentLow = 0;
  for (const e of recent) {
    if (e.selfScore < 5.0) {
      currentLow++;
      maxConsecutiveLow = Math.max(maxConsecutiveLow, currentLow);
    } else {
      currentLow = 0;
    }
  }

  console.log(`[supervisor] 品質サマリ (直近${recent.length}件):`);
  console.log(`  平均スコア: ${avgScore.toFixed(1)}`);
  console.log(`  最大連続低スコア(<5.0): ${maxConsecutiveLow}件`);

  if (maxConsecutiveLow >= 3) {
    console.warn("[supervisor] 警告: selfScore < 5.0 が3件以上連続しています");
  }
  if (avgScore < 6.0) {
    console.warn(`[supervisor] 警告: 平均スコアが ${avgScore.toFixed(1)} で低めです`);
  }
}

// ─── 週次レポート生成 ───────────────────────────────

function getWeekLabel() {
  const d = new Date();
  const year = d.getFullYear();
  const utc = new Date(Date.UTC(d.getFullYear(), d.getMonth(), d.getDate()));
  const dayNum = utc.getUTCDay() || 7;
  utc.setUTCDate(utc.getUTCDate() + 4 - dayNum);
  const yearStart = new Date(Date.UTC(utc.getUTCFullYear(), 0, 1));
  const weekNo = Math.ceil(((utc - yearStart) / 86400000 + 1) / 7);
  return `${year}-W${String(weekNo).padStart(2, "0")}`;
}

async function generateWeeklyReport() {
  const history = loadPostHistory();
  const feedback = readJson("analyst-feedback.json");
  const ks = readJson("kill-switch.json") || { enabled: false };

  // Sheets からステータス集計
  let sheetsSummary = { total: 0, draft: 0, approved: 0, queued: 0, posted: 0, discarded: 0, ngCount: 0 };
  try {
    const sheets = getSheets();
    const res = await sheets.spreadsheets.values.get({
      spreadsheetId: process.env.X_SHEET_ID,
      range: `${DRAFT_SHEET}!A2:R`,
    });
    const rows = res.data.values || [];
    const oneWeekAgo = new Date();
    oneWeekAgo.setDate(oneWeekAgo.getDate() - 7);
    const cutoff = jstDateString(oneWeekAgo);

    for (const r of rows) {
      if (!r[0]) continue;
      const generatedAt = r[8] || "";
      if (generatedAt < cutoff) continue;
      sheetsSummary.total++;
      const status = r[6] || "draft";
      if (status in sheetsSummary) sheetsSummary[status]++;
      if (r[12] && r[12].trim()) sheetsSummary.ngCount++;
    }
  } catch (err) {
    console.warn(`[supervisor] Sheets取得エラー（スキップ）: ${err.message}`);
  }

  // post-history からスコア・パターン集計
  const entries = history.entries || [];
  const scores = entries.filter((e) => e.selfScore != null).map((e) => e.selfScore);
  const avgScore = scores.length > 0 ? scores.reduce((a, b) => a + b, 0) / scores.length : null;

  const patternDist = {};
  const axisSplit = {};
  for (const e of entries) {
    if (e.firstLinePattern) {
      patternDist[e.firstLinePattern] = (patternDist[e.firstLinePattern] || 0) + 1;
    }
    const ax = e.axis || "unknown";
    axisSplit[ax] = (axisSplit[ax] || 0) + 1;
  }

  // 警告収集
  const warnings = [];
  if (sheetsSummary.total > 0 && sheetsSummary.ngCount / sheetsSummary.total > 0.2) {
    warnings.push(`NG率: ${((sheetsSummary.ngCount / sheetsSummary.total) * 100).toFixed(0)}%`);
  }
  if (avgScore != null && avgScore < 7.0) {
    warnings.push(`平均スコア低下: ${avgScore.toFixed(1)}`);
  }

  // 記事パイプラインサマリ
  const articles = readJson("articles.json") || [];
  const autoArticles = articles.filter((a) => a.autoGenerated);
  const recentAuto = autoArticles.filter((a) => {
    const created = new Date(a.createdAt);
    const oneWeekAgo = new Date();
    oneWeekAgo.setDate(oneWeekAgo.getDate() - 7);
    return created >= oneWeekAgo;
  });

  const articleSummary = {
    totalAutoGenerated: autoArticles.length,
    thisWeek: recentAuto.length,
    published: recentAuto.filter((a) => a.status === "published").length,
    draft: recentAuto.filter((a) => a.status === "draft").length,
    avgQualityScore: recentAuto.length > 0
      ? Number((recentAuto.reduce((s, a) => s + (a.qualityScore || 0), 0) / recentAuto.length).toFixed(1))
      : null,
  };

  // X 経由アフィリエイトクリック集計（affiliate-clicks.json）
  let xClickSummary = { total: 0, amazon: 0, rakuten: 0, topPages: [] };
  try {
    const clicksPath = path.join(DATA_DIR, "affiliate-clicks.json");
    if (fs.existsSync(clicksPath)) {
      const clicks = JSON.parse(fs.readFileSync(clicksPath, "utf-8"));
      const oneWeekAgo = new Date();
      oneWeekAgo.setDate(oneWeekAgo.getDate() - 7);
      const cutoff = jstDateString(oneWeekAgo);
      const recentClicks = clicks.filter(
        (c) => (c.timestamp || c.clicked_at || "") >= cutoff &&
                (c.source === "x" || (c.utm_source === "x"))
      );
      xClickSummary.total = recentClicks.length;
      xClickSummary.amazon = recentClicks.filter((c) => c.store === "amazon").length;
      xClickSummary.rakuten = recentClicks.filter((c) => c.store === "rakuten").length;
      // ページ別集計 top5
      const pageCount = {};
      for (const c of recentClicks) {
        const pg = c.path || c.page_path || "unknown";
        pageCount[pg] = (pageCount[pg] || 0) + 1;
      }
      xClickSummary.topPages = Object.entries(pageCount)
        .sort((a, b) => b[1] - a[1])
        .slice(0, 5)
        .map(([path, count]) => ({ path, count }));
    }
  } catch (err) {
    console.warn(`[supervisor] affiliate-clicks.json 読み込みエラー（スキップ）: ${err.message}`);
  }

  const report = {
    week: getWeekLabel(),
    generatedAt: jstIsoString(),
    summary: {
      totalGenerated: sheetsSummary.total,
      approved: sheetsSummary.approved,
      posted: sheetsSummary.posted,
      discarded: sheetsSummary.discarded,
      avgSelfScore: avgScore != null ? Number(avgScore.toFixed(1)) : null,
      ngRate: sheetsSummary.total > 0
        ? Number((sheetsSummary.ngCount / sheetsSummary.total).toFixed(2))
        : 0,
    },
    scoresTrend: scores.slice(-20),
    patternDistribution: patternDist,
    axisSplit,
    topPerformingTypes: feedback?.topPerformingTypes || [],
    warnings,
    killSwitchEvents: ks.enabled ? [{ reason: ks.reason, enabledAt: ks.enabledAt }] : [],
    articlePipeline: articleSummary,
    xAffiliateClicks: xClickSummary,
  };

  writeJson("weekly-report.json", report);
  console.log(`[supervisor] 週次レポート生成: ${report.week}`);
  console.log(`  生成: ${report.summary.totalGenerated} / 投稿済: ${report.summary.posted} / 平均スコア: ${report.summary.avgSelfScore ?? "N/A"}`);
  if (warnings.length > 0) {
    console.log(`  警告: ${warnings.join(", ")}`);
  }
}

// ─── エントリポイント ────────────────────────────────

const opts = parseArgs();

if (!opts.action) {
  console.log("使い方: --check | --kill <reason> | --resume | --backup | --quality-check | --weekly-report | --evaluate-article <id> [--cycle n]");
  process.exit(0);
}

switch (opts.action) {
  case "kill":
    enableKillSwitch(opts.reason);
    break;
  case "resume":
    disableKillSwitch();
    break;
  case "check":
    await runAnomalyCheck();
    break;
  case "backup":
    await runBackup();
    break;
  case "quality-check":
    runQualityCheck();
    break;
  case "weekly-report":
    await generateWeeklyReport();
    break;
  case "evaluate-article":
    evaluateArticle(opts.articleId, opts.cycle);
    break;
}
