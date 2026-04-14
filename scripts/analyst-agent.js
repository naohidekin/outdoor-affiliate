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
import Anthropic from "@anthropic-ai/sdk";
import {
  loadEnv,
  readJson,
  writeJson,
  checkKillSwitch,
  loadPostHistory,
  ipv4Fetch,
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

// ─── 1行目パターン深層分析 ──────────────────────────

/**
 * 投稿履歴の1行目パターンとエンゲージメントの相関を分析。
 * どのパターンがいいね・ブクマ・リプライを稼ぐかをデータで出す。
 */
function analyzeFirstLinePatterns(entries) {
  const patternStats = {};

  for (const entry of entries) {
    const pattern = entry.firstLinePattern;
    if (!pattern) continue;

    if (!patternStats[pattern]) {
      patternStats[pattern] = {
        count: 0,
        selfScores: [],
        likes: [],
        bookmarks: [],
        replies: [],
        impressions: [],
        bestPost: null,
        bestScore: 0,
      };
    }

    const s = patternStats[pattern];
    s.count++;
    if (entry.selfScore != null) s.selfScores.push(entry.selfScore);

    if (entry.engagements) {
      const e = entry.engagements;
      s.likes.push(e.likes || 0);
      s.bookmarks.push(e.bookmarks || 0);
      s.replies.push(e.replies || 0);
      s.impressions.push(e.impressions || 0);

      const engScore = (e.bookmarks || 0) * 3 + (e.likes || 0) + (e.replies || 0) * 2;
      if (engScore > s.bestScore) {
        s.bestScore = engScore;
        s.bestPost = {
          text: (entry.text || "").slice(0, 80),
          type: entry.type,
          likes: e.likes,
          bookmarks: e.bookmarks,
          replies: e.replies,
        };
      }
    }
  }

  // 集計 → ランキング
  const avg = (arr) => arr.length > 0 ? arr.reduce((a, b) => a + b, 0) / arr.length : 0;

  const ranking = Object.entries(patternStats)
    .map(([pattern, s]) => ({
      pattern,
      count: s.count,
      avgSelfScore: Number(avg(s.selfScores).toFixed(1)),
      avgLikes: Number(avg(s.likes).toFixed(1)),
      avgBookmarks: Number(avg(s.bookmarks).toFixed(1)),
      avgReplies: Number(avg(s.replies).toFixed(1)),
      avgImpressions: Number(avg(s.impressions).toFixed(0)),
      // ブクマ×3 + いいね + リプライ×2 のスコア（ブクマ最重視）
      engagementScore: Number(
        (avg(s.bookmarks) * 3 + avg(s.likes) + avg(s.replies) * 2).toFixed(1)
      ),
      bestPost: s.bestPost,
      hasEngagementData: s.likes.length > 0,
    }))
    .sort((a, b) => b.engagementScore - a.engagementScore);

  return {
    ranking,
    topPatterns: ranking.filter((r) => r.hasEngagementData).slice(0, 3).map((r) => r.pattern),
    weakPatterns: ranking.filter((r) => r.hasEngagementData && r.engagementScore < 1).map((r) => r.pattern),
    totalAnalyzed: entries.filter((e) => e.firstLinePattern).length,
  };
}

/**
 * 自分の高エンゲージメント投稿 + YouTube動画タイトルから
 * バズる1行目をコレクションして buzz-first-lines.json に蓄積。
 */
async function collectBuzzFirstLines(client, feedback) {
  const buzzData = readJson("buzz-first-lines.json") || { version: 1, lastUpdated: null, lines: [] };
  const existingTexts = new Set(buzzData.lines.map((l) => l.text));
  const newLines = [];

  // ソース1: 自分の高エンゲージメント投稿の1行目
  if (feedback.topEngagementPosts && feedback.topEngagementPosts.length > 0) {
    for (const post of feedback.topEngagementPosts) {
      const firstLine = (post.textPreview || "").split("\n")[0].trim();
      if (firstLine && firstLine.length >= 10 && !existingTexts.has(firstLine)) {
        newLines.push({
          text: firstLine,
          source: "own_post",
          postType: post.postType,
          likes: post.likes,
          bookmarks: post.bookmarks,
          replies: post.replies,
          collectedAt: new Date().toISOString().slice(0, 10),
          pattern: null, // Claude で後で分類
        });
        existingTexts.add(firstLine);
      }
    }
  }

  // ソース2: YouTubeリサーチで取得した動画タイトル（バズの1行目に相当）
  const seeds = readJson("x-content-seeds.json");
  if (seeds?.seeds) {
    const ytSeeds = seeds.seeds.filter(
      (s) => s.source === "youtube" && s.bookmarkPotential === "high" && s.hint
    );
    for (const seed of ytSeeds.slice(-20)) {
      const firstLine = seed.hint.split("。")[0] + "。";
      if (firstLine.length >= 10 && !existingTexts.has(firstLine)) {
        newLines.push({
          text: firstLine,
          source: "youtube_title",
          axis: seed.axis,
          collectedAt: new Date().toISOString().slice(0, 10),
          pattern: null,
        });
        existingTexts.add(firstLine);
      }
    }
  }

  if (newLines.length === 0) {
    console.log("[analyst] 新規バズ1行目なし");
    return;
  }

  // Claude でパターン分類
  if (client) {
    const patternsData = readJson("first-line-patterns.json");
    const patternNames = patternsData?.categories?.map((c) => `${c.id}: ${c.name}`) || [];

    const prompt = `以下の投稿の1行目をパターン分類してください。

## パターン一覧
${patternNames.join("\n")}

## 分類対象
${newLines.map((l, i) => `${i}: ${l.text}`).join("\n")}

## 出力（JSONのみ）
[${newLines.map((_, i) => `"pattern_id_for_${i}"`).join(", ")}]

各要素はパターンIDの文字列。該当なしなら "other"。`;

    try {
      const response = await client.messages.create({
        model: "claude-sonnet-4-20250514",
        max_tokens: 500,
        messages: [{ role: "user", content: prompt }],
      });
      const text = response.content[0].text;
      const jsonMatch = text.match(/\[[\s\S]*\]/);
      if (jsonMatch) {
        const patterns = JSON.parse(jsonMatch[0]);
        for (let i = 0; i < Math.min(patterns.length, newLines.length); i++) {
          newLines[i].pattern = patterns[i] || "other";
        }
      }
    } catch (err) {
      console.warn(`[analyst] パターン分類失敗: ${err.message}`);
    }
  }

  // 保存（古いものは500件まで保持）
  buzzData.lines.push(...newLines);
  if (buzzData.lines.length > 500) {
    buzzData.lines = buzzData.lines.slice(-500);
  }
  buzzData.lastUpdated = new Date().toISOString();
  writeJson("buzz-first-lines.json", buzzData);
  console.log(`[analyst] buzz-first-lines.json に ${newLines.length}件追加（合計${buzzData.lines.length}件）`);
}

// ─── パフォーマンス分析 ──────────────────────────────

// ─── Xエンゲージメントデータ読み込み ───────────────────

function loadEngagementData() {
  const data = readJson("x-engagement.json");
  if (!data || !data.recentMetrics) return null;
  return data;
}

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

  // ─── 1行目パターン × エンゲージメント 深層分析 ───────

  const firstLineAnalysis = analyzeFirstLinePatterns(history.entries);

  // ─── Xエンゲージメントデータ分析 ───────────────────
  const engData = loadEngagementData();
  const engagementByType = {};
  const topEngagementPosts = [];
  let replyThemes = [];

  if (engData && engData.recentMetrics && engData.recentMetrics.length > 0) {
    // タイプ別エンゲージメント集計
    for (const m of engData.recentMetrics) {
      if (!engagementByType[m.postType]) {
        engagementByType[m.postType] = { likes: 0, bookmarks: 0, retweets: 0, replies: 0, impressions: 0, count: 0 };
      }
      const t = engagementByType[m.postType];
      t.likes += m.likes || 0;
      t.bookmarks += m.bookmarks || 0;
      t.retweets += m.retweets || 0;
      t.replies += m.replies || 0;
      t.impressions += m.impressions || 0;
      t.count++;
    }

    // ブクマ+いいね上位の投稿
    const sorted = [...engData.recentMetrics].sort(
      (a, b) => ((b.bookmarks || 0) + (b.likes || 0)) - ((a.bookmarks || 0) + (a.likes || 0))
    );
    for (const s of sorted.slice(0, 5)) {
      topEngagementPosts.push({
        postType: s.postType,
        textPreview: s.textPreview,
        likes: s.likes,
        bookmarks: s.bookmarks,
        retweets: s.retweets,
        replies: s.replies,
      });
    }

    // リプライ内容のテーマ抽出（質問・リクエストを検出）
    if (engData.replyDigest && engData.replyDigest.length > 0) {
      replyThemes = engData.replyDigest
        .slice(0, 10)
        .map((r) => r.text?.slice(0, 80))
        .filter(Boolean);
    }
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

  // エンゲージメントベースのヒント
  for (const [type, stats] of Object.entries(engagementByType)) {
    const avgBookmarks = stats.count > 0 ? (stats.bookmarks / stats.count).toFixed(1) : 0;
    const avgLikes = stats.count > 0 ? (stats.likes / stats.count).toFixed(1) : 0;
    if (avgBookmarks >= 3) {
      writerHints.push(`${type} はブクマ率が高い（平均${avgBookmarks}）→ このタイプの保存版コンテンツを増やす`);
    }
    if (avgLikes >= 5) {
      writerHints.push(`${type} はいいね率が高い（平均${avgLikes}）→ 好調`);
    }
    if (stats.count >= 3 && stats.bookmarks === 0 && stats.likes < stats.count) {
      writerHints.push(`${type} の反応が薄い → 切り口や構成を変えてみる`);
    }
  }

  if (topEngagementPosts.length > 0) {
    const top = topEngagementPosts[0];
    writerHints.push(`直近トップ投稿: [${top.postType}]「${top.textPreview}」(♥${top.likes} 🔖${top.bookmarks}) → 似た切り口を再活用`);
  }

  if (replyThemes.length > 0) {
    writerHints.push(`読者の反応/質問: ${replyThemes.slice(0, 3).join(" | ")}`);
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
    version: 3,
    updatedAt: now.toISOString(),
    period: `${periodStart.toISOString().slice(0, 10)} ~ ${now.toISOString().slice(0, 10)}`,
    topPerformingTypes,
    lowPerformingTypes,
    effectivePatterns,
    avoidPatterns,
    axisFeedback,
    seasonalInsight,
    writerHints,
    engagementByType,
    topEngagementPosts,
    replyThemes,
    firstLineAnalysis,
  };
}

// ─── Claude API でライター向けディレクティブ生成 ────────

async function generateWriterDirectives(feedback) {
  const apiKey = process.env.ANTHROPIC_API_KEY;
  if (!apiKey) {
    console.warn("[analyst] ANTHROPIC_API_KEY 未設定。ディレクティブ生成スキップ。");
    return [];
  }

  // データが全くない場合はスキップ
  const hasEngagement = Object.keys(feedback.engagementByType).length > 0;
  const hasPosts = feedback.topPerformingTypes.length > 0 || feedback.lowPerformingTypes.length > 0;
  const hasPatterns = feedback.effectivePatterns.length > 0 || feedback.avoidPatterns.length > 0;

  if (!hasEngagement && !hasPosts && !hasPatterns) {
    console.log("[analyst] 分析データ不足。初期ディレクティブを生成します。");
    return generateInitialDirectives();
  }

  const client = new Anthropic({ apiKey, fetch: ipv4Fetch, maxRetries: 3 });

  const dataReport = `## 分析期間: ${feedback.period}

## タイプ別エンゲージメント
${Object.entries(feedback.engagementByType).map(([type, s]) =>
  `- ${type}: いいね合計${s.likes} ブクマ合計${s.bookmarks} RT${s.retweets} リプライ${s.replies} インプレッション${s.impressions} (${s.count}件)`
).join("\n") || "データなし"}

## トップ投稿（エンゲージメント順）
${feedback.topEngagementPosts.map((p, i) =>
  `${i + 1}. [${p.postType}] ♥${p.likes} 🔖${p.bookmarks} RT${p.retweets} 💬${p.replies} — ${p.textPreview}`
).join("\n") || "データなし"}

## 高パフォーマンスタイプ（承認率高・NG少）: ${feedback.topPerformingTypes.join(", ") || "なし"}
## 低パフォーマンスタイプ（NG率高）: ${feedback.lowPerformingTypes.join(", ") || "なし"}

## 有効な書き出しパターン
${feedback.effectivePatterns.map((p) => `- ${p.pattern}: ${p.reason}`).join("\n") || "データなし"}

## NG頻出パターン
${feedback.avoidPatterns.map((p) => `- ${p.pattern}: ${p.reason}`).join("\n") || "なし"}

## 軸別フィードバック
${Object.entries(feedback.axisFeedback).map(([axis, msg]) => `- ${axis}: ${msg}`).join("\n") || "なし"}

## 読者のリプライ内容
${feedback.replyThemes.slice(0, 5).join("\n") || "なし"}

## 1行目パターン × エンゲージメント分析
${feedback.firstLineAnalysis?.ranking?.slice(0, 8).map((r) =>
  `- ${r.pattern}: エンゲージメントスコア${r.engagementScore} (♥${r.avgLikes} 🔖${r.avgBookmarks} 💬${r.avgReplies}) ${r.count}件`
).join("\n") || "データ不足"}
伸びるパターン: ${feedback.firstLineAnalysis?.topPatterns?.join(", ") || "判定不可"}
弱いパターン: ${feedback.firstLineAnalysis?.weakPatterns?.join(", ") || "判定不可"}

## 季節情報: ${feedback.seasonalInsight}`;

  const prompt = `あなたはXアカウント運用の分析官です。以下のデータを読み、ライター（投稿生成AI）への具体的な指示書を作成してください。

${dataReport}

## あなたの仕事
上記データから「何が伸びて、何が伸びなかったか」を判断し、次の投稿バッチへの**具体的な指示**を出してください。

## 指示の出し方
- 「〜を増やせ」「〜は控えろ」「〜の切り口に変えろ」のように断言調で
- 数字の根拠を必ず添える（「いいね平均12.3 vs 4.7だから」等）
- 読者のリプライから拾えるネタがあれば指示に含める
- 季節要因も考慮する
- データが少ない場合は「まだ判断できない。引き続きデータ蓄積」と正直に言う

## 出力形式（JSONのみ、他のテキスト不要）
[
  {
    "directive": "指示内容（1文で。命令調で）",
    "reason": "根拠（数字を含めて1〜2文）",
    "priority": "high / medium / low",
    "appliesTo": ["対象のpost_type。全体なら 'all'"]
  }
]

5〜10件。重要度順に並べてください。`;

  try {
    const response = await client.messages.create({
      model: "claude-sonnet-4-20250514",
      max_tokens: 2000,
      messages: [{ role: "user", content: prompt }],
    });

    const text = response.content[0].text;
    const jsonMatch = text.match(/\[[\s\S]*\]/);
    if (!jsonMatch) return [];
    return JSON.parse(jsonMatch[0]);
  } catch (err) {
    console.warn(`[analyst] ディレクティブ生成失敗: ${err.message}`);
    return [];
  }
}

/** データ蓄積前の初期ディレクティブ（安全なデフォルト） */
function generateInitialDirectives() {
  const month = new Date().getMonth() + 1;
  return [
    {
      directive: "【保存版】【ブクマ推奨】を冒頭に使った情報密度の高い投稿を各タイプ1件以上入れる",
      reason: "アカウント育成フェーズ。ブクマ数はXアルゴリズムで最も評価が高い指標",
      priority: "high",
      appliesTo: ["outdoor_tip", "gear_thread", "seasonal_hook"],
    },
    {
      directive: "1行目は断言型 or 数字入りで始める。疑問形は3割以下に抑える",
      reason: "データ蓄積前だが、一般的にX投稿は断言型の1行目がインプレッション高い",
      priority: "high",
      appliesTo: ["all"],
    },
    {
      directive: "poll_question は選択肢を2択にして対立軸を明確にする",
      reason: "2択の方が4択より回答率が高い傾向。議論が起きやすい",
      priority: "medium",
      appliesTo: ["poll_question"],
    },
    {
      directive: `${month}月の季節ネタを全投稿の3割以上に含める`,
      reason: "季節性の高い投稿は検索流入とタイムライン表示の両方で有利",
      priority: "medium",
      appliesTo: ["all"],
    },
    {
      directive: "数値データ（○g, ○円, ○分, ○℃）を投稿に必ず1つ以上含める",
      reason: "具体的数値がある投稿はブクマ率が高い傾向。信頼性と保存価値の両方が上がる",
      priority: "medium",
      appliesTo: ["outdoor_tip", "gear_thread", "doc_health_tip"],
    },
  ];
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

  // Claude クライアント準備
  const apiKey = process.env.ANTHROPIC_API_KEY;
  const client = apiKey ? new Anthropic({ apiKey }) : null;

  // バズ1行目コレクション更新
  if (!opts.dryRun) {
    console.log("\n[analyst] バズ1行目を収集中...");
    await collectBuzzFirstLines(client, feedback);
  }

  // 1行目パターン分析の表示
  if (feedback.firstLineAnalysis && feedback.firstLineAnalysis.ranking.length > 0) {
    console.log("\n[analyst] 1行目パターン × エンゲージメント:");
    for (const r of feedback.firstLineAnalysis.ranking.slice(0, 5)) {
      const eng = r.hasEngagementData
        ? ` ♥${r.avgLikes} 🔖${r.avgBookmarks} 💬${r.avgReplies}`
        : " (エンゲージメント未取得)";
      console.log(`  ${r.pattern}: スコア${r.engagementScore}${eng} (${r.count}件)`);
      if (r.bestPost) {
        console.log(`    Best: ${r.bestPost.text.slice(0, 50)}`);
      }
    }
  }

  // Claude でライターへのディレクティブ生成
  console.log("\n[analyst] ライターへのディレクティブを生成中...");
  const directives = await generateWriterDirectives(feedback);
  feedback.writerDirectives = directives;

  // ディレクティブを writerHints にも変換（後方互換）
  for (const d of directives) {
    const prefix = d.priority === "high" ? "【重要】" : "";
    const scope = d.appliesTo.includes("all") ? "" : ` [${d.appliesTo.join(",")}]`;
    feedback.writerHints.push(`${prefix}${d.directive}${scope} — ${d.reason}`);
  }

  // 結果表示
  console.log("\n[analyst] フィードバックサマリ:");
  console.log(`  高パフォーマンスタイプ: ${feedback.topPerformingTypes.join(", ") || "なし"}`);
  console.log(`  低パフォーマンスタイプ: ${feedback.lowPerformingTypes.join(", ") || "なし"}`);
  console.log(`  有効パターン: ${feedback.effectivePatterns.length}件`);
  console.log(`  回避パターン: ${feedback.avoidPatterns.length}件`);
  console.log(`  季節インサイト: ${feedback.seasonalInsight}`);
  if (Object.keys(feedback.engagementByType).length > 0) {
    console.log("  タイプ別エンゲージメント:");
    for (const [type, stats] of Object.entries(feedback.engagementByType)) {
      console.log(`    ${type}: ♥${stats.likes} 🔖${stats.bookmarks} RT${stats.retweets} 💬${stats.replies} (${stats.count}件)`);
    }
  }
  if (feedback.topEngagementPosts.length > 0) {
    console.log("  トップ投稿:");
    for (const p of feedback.topEngagementPosts.slice(0, 3)) {
      console.log(`    [${p.postType}] ♥${p.likes} 🔖${p.bookmarks} — ${p.textPreview}`);
    }
  }
  if (feedback.replyThemes.length > 0) {
    console.log(`  読者リプライ: ${feedback.replyThemes.length}件`);
  }
  if (feedback.writerDirectives && feedback.writerDirectives.length > 0) {
    console.log("  ライターへのディレクティブ:");
    for (const d of feedback.writerDirectives) {
      const icon = d.priority === "high" ? "🔴" : d.priority === "medium" ? "🟡" : "⚪";
      console.log(`    ${icon} ${d.directive}`);
      console.log(`      → ${d.reason}`);
      console.log(`      対象: ${d.appliesTo.join(", ")}`);
    }
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
