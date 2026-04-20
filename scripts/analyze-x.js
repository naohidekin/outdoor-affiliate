#!/usr/bin/env node

/**
 * X 投稿分析スクリプト
 * 投稿済みツイートのメトリクス（インプレッション、いいね、RT、リンクCTR）を取得し
 * data/x-analytics/ に保存する。post-history.json の engagements も更新する。
 *
 * 使い方:
 *   node scripts/analyze-x.js           # 直近7日のポスト分析
 *   node scripts/analyze-x.js --days=14 # 期間指定
 *   node scripts/analyze-x.js --dry-run # 保存なし
 */

import { TwitterApi } from "twitter-api-v2";
import { google } from "googleapis";
import fs from "fs";
import path from "path";
import { fileURLToPath } from "url";
import { loadEnv, readJson, writeJson, loadPostHistory } from "../src/lib/x-agent-utils.mjs";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const DATA_DIR = path.join(__dirname, "..", "data");

loadEnv();

const QUEUE_SHEET = "X投稿管理";

// === CLI オプション ===

function parseArgs() {
  const args = process.argv.slice(2);
  const opts = { days: 7, dryRun: false };
  for (let i = 0; i < args.length; i++) {
    const arg = args[i];
    const eqIdx = arg.indexOf("=");
    const key = eqIdx !== -1 ? arg.slice(0, eqIdx) : arg;
    const val = eqIdx !== -1 ? arg.slice(eqIdx + 1) : args[i + 1];
    switch (key) {
      case "--days":    opts.days = parseInt(val, 10) || 7; if (eqIdx === -1) i++; break;
      case "--dry-run": opts.dryRun = true; break;
    }
  }
  return opts;
}

// === Google Sheets ===

async function getSheets() {
  const credentials = JSON.parse(process.env.GOOGLE_CREDENTIALS);
  const auth = new google.auth.GoogleAuth({
    credentials,
    scopes: ["https://www.googleapis.com/auth/spreadsheets"],
  });
  return google.sheets({ version: "v4", auth });
}

async function getPostedRows(days) {
  const sheets = await getSheets();
  const spreadsheetId = process.env.X_SHEET_ID;

  const res = await sheets.spreadsheets.values.get({
    spreadsheetId,
    range: `${QUEUE_SHEET}!A2:J`,
  });

  const rows = res.data.values || [];
  const cutoff = new Date();
  cutoff.setDate(cutoff.getDate() - days);

  return rows
    .filter((r) => {
      if (r[0] !== "posted") return false;
      const postUrl = r[7] || "";
      if (!postUrl.includes("x.com")) return false;
      const postedAt = r[6];
      if (postedAt && new Date(postedAt) < cutoff) return false;
      return true;
    })
    .map((r, i) => ({
      rowIndex: i + 2,
      postType: r[1] || "",
      text: r[2] || "",
      postedAt: r[6] || "",
      imageUrl: r[3] || "",
      postUrl: r[7] || "",
      tweetId: (r[7] || "").match(/status\/(\d+)/)?.[1] || null,
    }))
    .filter((r) => r.tweetId);
}

// === X API クライアント ===

function getXClient() {
  return new TwitterApi({
    appKey: process.env.X_API_KEY,
    appSecret: process.env.X_API_SECRET,
    accessToken: process.env.X_ACCESS_TOKEN,
    accessSecret: process.env.X_ACCESS_SECRET,
  });
}

// === メトリクス取得 ===

async function fetchMetrics(client, tweetIds) {
  const results = {};
  // 100件ずつバッチ処理
  const chunks = [];
  for (let i = 0; i < tweetIds.length; i += 100) {
    chunks.push(tweetIds.slice(i, i + 100));
  }

  for (const chunk of chunks) {
    try {
      const response = await client.v2.tweets(chunk, {
        "tweet.fields": ["public_metrics", "organic_metrics", "created_at"],
      });

      for (const tweet of response.data || []) {
        const pub = tweet.public_metrics || {};
        const org = tweet.organic_metrics || {};
        results[tweet.id] = {
          likes: pub.like_count || 0,
          retweets: pub.retweet_count || 0,
          replies: pub.reply_count || 0,
          bookmarks: pub.bookmark_count || 0,
          impressions: pub.impression_count || org.impression_count || 0,
          linkClicks: org.url_link_clicks || 0,
          userProfileClicks: org.user_profile_clicks || 0,
          engagementScore:
            (pub.like_count || 0) * 2 +
            (pub.retweet_count || 0) * 3 +
            (pub.reply_count || 0) +
            (pub.bookmark_count || 0) * 2,
        };
      }
    } catch (err) {
      console.warn(`[analyze] メトリクス取得エラー (${chunk.length}件): ${err.message}`);
    }
  }

  return results;
}

// === メディアあり/なし効果比較 ===

function analyzeMediaEffect(rows, metricsMap) {
  const withMedia = { count: 0, totalEngagement: 0, totalImpressions: 0 };
  const noMedia = { count: 0, totalEngagement: 0, totalImpressions: 0 };

  for (const row of rows) {
    const m = metricsMap[row.tweetId];
    if (!m) continue;
    const bucket = row.imageUrl ? withMedia : noMedia;
    bucket.count++;
    bucket.totalEngagement += m.engagementScore;
    bucket.totalImpressions += m.impressions;
  }

  const calc = (b) => b.count === 0 ? null : {
    count: b.count,
    avgEngagement: Math.round((b.totalEngagement / b.count) * 10) / 10,
    avgImpressions: Math.round(b.totalImpressions / b.count),
  };

  return { withMedia: calc(withMedia), noMedia: calc(noMedia) };
}

// === パターン別パフォーマンス集計 ===

function aggregateByType(rows, metricsMap) {
  const byType = {};
  for (const row of rows) {
    const m = metricsMap[row.tweetId];
    if (!m) continue;

    if (!byType[row.postType]) {
      byType[row.postType] = { count: 0, totalImpressions: 0, totalLikes: 0, totalRT: 0, totalBookmarks: 0, totalLinkClicks: 0, totalEngagementScore: 0 };
    }
    const t = byType[row.postType];
    t.count++;
    t.totalImpressions += m.impressions;
    t.totalLikes += m.likes;
    t.totalRT += m.retweets;
    t.totalBookmarks += m.bookmarks;
    t.totalLinkClicks += m.linkClicks;
    t.totalEngagementScore += m.engagementScore;
  }

  return Object.fromEntries(
    Object.entries(byType).map(([type, data]) => [
      type,
      {
        count: data.count,
        avgImpressions: Math.round(data.totalImpressions / data.count),
        avgLikes: Math.round((data.totalLikes / data.count) * 10) / 10,
        avgRT: Math.round((data.totalRT / data.count) * 10) / 10,
        avgBookmarks: Math.round((data.totalBookmarks / data.count) * 10) / 10,
        avgLinkClicks: Math.round((data.totalLinkClicks / data.count) * 10) / 10,
        avgEngagementScore: Math.round((data.totalEngagementScore / data.count) * 10) / 10,
      },
    ])
  );
}

// === post-history.json の engagements 更新 ===

function updatePostHistory(rows, metricsMap) {
  const historyPath = path.join(DATA_DIR, "post-history.json");
  if (!fs.existsSync(historyPath)) return;

  const history = JSON.parse(fs.readFileSync(historyPath, "utf-8"));
  let updated = 0;

  for (const row of rows) {
    const m = metricsMap[row.tweetId];
    if (!m) continue;

    // テキストの先頭100文字で照合（IDは保存されていない）
    const preview = row.text.slice(0, 100);
    const entry = history.entries?.find((e) => e.text?.startsWith(preview.slice(0, 50)));
    if (entry) {
      entry.engagements = {
        likes: m.likes,
        retweets: m.retweets,
        replies: m.replies,
        bookmarks: m.bookmarks,
        impressions: m.impressions,
        linkClicks: m.linkClicks,
        engagementScore: m.engagementScore,
        tweetId: row.tweetId,
        measuredAt: new Date().toISOString().slice(0, 10),
      };
      updated++;
    }
  }

  if (updated > 0) {
    fs.writeFileSync(historyPath, JSON.stringify(history, null, 2) + "\n", "utf-8");
    console.log(`post-history.json を ${updated}件更新`);
  }
}

// === analyst-feedback.json にインサイト追記 ===

function appendAnalystInsight(typeStats) {
  const feedbackPath = path.join(DATA_DIR, "analyst-feedback.json");
  let feedback = {};
  if (fs.existsSync(feedbackPath)) {
    feedback = JSON.parse(fs.readFileSync(feedbackPath, "utf-8"));
  }

  if (!feedback.performanceStats) feedback.performanceStats = {};
  const today = new Date().toISOString().slice(0, 10);
  feedback.performanceStats[today] = typeStats;

  // 高パフォーマンスタイプをライターディレクティブに追記
  const sorted = Object.entries(typeStats)
    .filter(([, s]) => s.count >= 2)
    .sort(([, a], [, b]) => b.avgEngagementScore - a.avgEngagementScore);

  if (sorted.length > 0) {
    const topType = sorted[0][0];
    const topStats = sorted[0][1];
    const hint = `${topType}が高エンゲージ(avg score: ${topStats.avgEngagementScore})。このタイプの構成を優先すること。`;

    if (!feedback.writerHints) feedback.writerHints = [];
    // 同じタイプの古いヒントを置換
    feedback.writerHints = feedback.writerHints.filter((h) => !h.includes(topType));
    feedback.writerHints.unshift(`[${today}] ` + hint);
    // 最大10件に制限
    feedback.writerHints = feedback.writerHints.slice(0, 10);
  }

  return feedback;
}

// === メイン ===

async function runAnalyze(opts) {
  const spreadsheetId = process.env.X_SHEET_ID;
  if (!spreadsheetId) {
    console.error("X_SHEET_ID が設定されていません");
    process.exit(1);
  }

  console.log(`直近${opts.days}日間の投稿を分析中...`);

  // ポスト済み行を取得
  let postedRows;
  try {
    postedRows = await getPostedRows(opts.days);
  } catch (err) {
    console.error(`Sheets読み取りエラー: ${err.message}`);
    process.exit(1);
  }

  if (postedRows.length === 0) {
    console.log("分析対象の投稿がありません");
    return;
  }

  console.log(`対象ツイート: ${postedRows.length}件`);

  // メトリクス取得
  const client = getXClient();
  const tweetIds = postedRows.map((r) => r.tweetId);
  const metricsMap = await fetchMetrics(client, tweetIds);

  const fetchedCount = Object.keys(metricsMap).length;
  console.log(`メトリクス取得: ${fetchedCount}/${tweetIds.length}件`);

  // タイプ別集計
  const typeStats = aggregateByType(postedRows, metricsMap);
  const mediaEffect = analyzeMediaEffect(postedRows, metricsMap);

  // 結果表示
  console.log("\n===== タイプ別パフォーマンス =====");
  for (const [type, stats] of Object.entries(typeStats).sort((a, b) => b[1].avgEngagementScore - a[1].avgEngagementScore)) {
    console.log(`[${type}] (${stats.count}件) imp:${stats.avgImpressions} ♥${stats.avgLikes} RT${stats.avgRT} 🔖${stats.avgBookmarks} CTR:${stats.avgLinkClicks} score:${stats.avgEngagementScore}`);
  }

  console.log("\n===== 画像（漫画）添付効果 =====");
  if (mediaEffect.withMedia) {
    console.log(`画像あり: ${mediaEffect.withMedia.count}件 | avg engagement: ${mediaEffect.withMedia.avgEngagement} | imp: ${mediaEffect.withMedia.avgImpressions}`);
  } else {
    console.log("画像あり: データなし");
  }
  if (mediaEffect.noMedia) {
    console.log(`画像なし: ${mediaEffect.noMedia.count}件 | avg engagement: ${mediaEffect.noMedia.avgEngagement} | imp: ${mediaEffect.noMedia.avgImpressions}`);
  }
  if (mediaEffect.withMedia && mediaEffect.noMedia) {
    const diff = mediaEffect.withMedia.avgEngagement - mediaEffect.noMedia.avgEngagement;
    const verdict = diff > 0 ? `+${diff.toFixed(1)} → 画像あり有利` : diff < 0 ? `${diff.toFixed(1)} → テキストのみ有利` : "差なし";
    console.log(`比較: ${verdict}`);
  }

  if (opts.dryRun) {
    console.log("\n[DRY RUN] 保存をスキップ");
    return;
  }

  // アナリティクス保存
  const analyticsDir = path.join(DATA_DIR, "x-analytics");
  if (!fs.existsSync(analyticsDir)) fs.mkdirSync(analyticsDir, { recursive: true });

  const today = new Date().toISOString().slice(0, 10);
  const outPath = path.join(analyticsDir, `${today}.json`);
  const outData = {
    date: today,
    analyzedDays: opts.days,
    totalPosts: postedRows.length,
    metricsAvailable: fetchedCount,
    byType: typeStats,
    mediaEffect,
    posts: postedRows.map((r) => ({
      tweetId: r.tweetId,
      postType: r.postType,
      postedAt: r.postedAt,
      postUrl: r.postUrl,
      metrics: metricsMap[r.tweetId] || null,
    })),
  };

  fs.writeFileSync(outPath, JSON.stringify(outData, null, 2) + "\n", "utf-8");
  console.log(`\n保存完了: ${outPath}`);

  // post-history.json 更新
  updatePostHistory(postedRows, metricsMap);

  // analyst-feedback.json 更新
  const feedback = appendAnalystInsight(typeStats);
  const feedbackPath = path.join(DATA_DIR, "analyst-feedback.json");
  fs.writeFileSync(feedbackPath, JSON.stringify(feedback, null, 2) + "\n", "utf-8");
  console.log("analyst-feedback.json を更新（次回生成に反映）");
}

const opts = parseArgs();
runAnalyze(opts).catch((err) => {
  console.error("エラー:", err.message);
  process.exit(1);
});
