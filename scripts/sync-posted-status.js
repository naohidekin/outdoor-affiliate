#!/usr/bin/env node

/**
 * 投稿ステータス同期スクリプト
 * 「X投稿管理」シートに存在するテキストと「下書き管理」シートを比較し、
 * queuedのポストをpostedに更新する
 *
 * 使い方:
 *   node scripts/sync-posted-status.js
 */

import { google } from "googleapis";
import { TwitterApi } from "twitter-api-v2";
import fs from "fs";
import path from "path";
import { fileURLToPath } from "url";
import { loadEnv, readJson, loadPostHistory, writeJson } from "../src/lib/x-agent-utils.mjs";

const __dirname = path.dirname(fileURLToPath(import.meta.url));

loadEnv();

const DRAFT_SHEET = "下書き管理";
const QUEUE_SHEET = "X投稿管理";

async function getSheets() {
  const credentials = JSON.parse(process.env.GOOGLE_CREDENTIALS);
  const auth = new google.auth.GoogleAuth({
    credentials,
    scopes: ["https://www.googleapis.com/auth/spreadsheets"],
  });
  return google.sheets({ version: "v4", auth });
}

async function syncPostedStatus() {
  const spreadsheetId = process.env.X_SHEET_ID;
  if (!spreadsheetId) {
    console.error("X_SHEET_ID が設定されていません");
    process.exit(1);
  }

  const sheets = await getSheets();

  // 「X投稿管理」シートからテキスト一覧を取得
  let postedTexts;
  try {
    const queueRes = await sheets.spreadsheets.values.get({
      spreadsheetId,
      range: `${QUEUE_SHEET}!A2:H`,
    });
    const queueRows = queueRes.data.values || [];
    postedTexts = new Set(queueRows.map((r) => r[2]?.trim()).filter(Boolean));
  } catch {
    console.log("X投稿管理シートが見つかりません");
    return;
  }

  // 「下書き管理」シートから全データを取得
  const draftRes = await sheets.spreadsheets.values.get({
    spreadsheetId,
    range: `${DRAFT_SHEET}!A2:J`,
  });
  const draftRows = draftRes.data.values || [];

  let updated = 0;
  const updatedIds = [];

  for (let i = 0; i < draftRows.length; i++) {
    const row = draftRows[i];
    const postId = row[0];
    const status = row[6];
    const text = row[2]?.trim();

    if (status === "queued" && text && postedTexts.has(text)) {
      const rowIndex = i + 2;
      await sheets.spreadsheets.values.update({
        spreadsheetId,
        range: `${DRAFT_SHEET}!G${rowIndex}:J${rowIndex}`,
        valueInputOption: "RAW",
        requestBody: {
          values: [["posted", row[7] || "", row[8] || "", new Date().toISOString()]],
        },
      });
      updated++;
      if (postId) updatedIds.push(postId);
      console.log(`  更新: ${text.slice(0, 40)}...`);
    }
  }

  // post-history.json の postedAt を更新
  if (updatedIds.length > 0) {
    const history = loadPostHistory();
    const now = new Date().toISOString();
    let historyUpdated = 0;
    for (const entry of history.entries) {
      if (updatedIds.includes(entry.id) && !entry.postedAt) {
        entry.postedAt = now;
        historyUpdated++;
      }
    }
    if (historyUpdated > 0) {
      writeJson("post-history.json", history);
      console.log(`post-history.json: ${historyUpdated}件の postedAt を更新`);
    }
  }

  console.log(`${updated}件のポストをpostedに更新しました`);
}

// ─── X API エンゲージメント取得 ──────────────────────

function getXClient() {
  const { X_API_KEY, X_API_SECRET, X_ACCESS_TOKEN, X_ACCESS_SECRET } = process.env;
  if (!X_API_KEY || !X_API_SECRET || !X_ACCESS_TOKEN || !X_ACCESS_SECRET) return null;
  return new TwitterApi({
    appKey: X_API_KEY,
    appSecret: X_API_SECRET,
    accessToken: X_ACCESS_TOKEN,
    accessSecret: X_ACCESS_SECRET,
  });
}

/**
 * 投稿済みツイートのエンゲージメント指標を X API から取得し、
 * post-history.json の各エントリに engagements フィールドを追加。
 * また x-engagement.json にリプライ内容を記録する。
 */
async function fetchEngagementData() {
  const xClient = getXClient();
  if (!xClient) {
    console.log("[engagement] X API キー未設定。スキップ。");
    return;
  }

  const spreadsheetId = process.env.X_SHEET_ID;
  if (!spreadsheetId) return;

  const sheets = await getSheets();

  // 「X投稿管理」シートから posted の行を取得（tweet ID = post_url から抽出）
  let queueRows;
  try {
    const queueRes = await sheets.spreadsheets.values.get({
      spreadsheetId,
      range: `${QUEUE_SHEET}!A2:I`,
    });
    queueRows = queueRes.data.values || [];
  } catch {
    console.log("[engagement] X投稿管理シートが見つかりません");
    return;
  }

  // 投稿から48時間〜14日のツイートのみメトリクス取得
  // 48時間未満はエンゲージメントが安定していないため取得しない
  const now = new Date();
  const twoWeeksAgo = new Date(now);
  twoWeeksAgo.setDate(twoWeeksAgo.getDate() - 14);
  const fortyEightHoursAgo = new Date(now);
  fortyEightHoursAgo.setHours(fortyEightHoursAgo.getHours() - 48);

  const tweetEntries = [];
  let skippedTooNew = 0;
  for (const row of queueRows) {
    if (row[0] !== "posted") continue;
    const postedAt = row[6];
    if (!postedAt) continue;
    const postedDate = new Date(postedAt);
    if (postedDate < twoWeeksAgo) continue;
    // 48時間ルール: 投稿直後のメトリクスは不安定なのでスキップ
    if (postedDate > fortyEightHoursAgo) {
      skippedTooNew++;
      continue;
    }
    const postUrl = row[7] || "";
    const tweetIdMatch = postUrl.match(/status\/(\d+)/);
    if (!tweetIdMatch) continue;
    tweetEntries.push({
      tweetId: tweetIdMatch[1],
      postType: row[1],
      text: (row[2] || "").slice(0, 60),
      postedAt,
    });
  }

  if (tweetEntries.length === 0) {
    console.log("[engagement] 追跡対象の投稿なし");
    return;
  }

  if (skippedTooNew > 0) {
    console.log(`[engagement] ${skippedTooNew}件は投稿から48時間未満のためスキップ`);
  }
  console.log(`[engagement] ${tweetEntries.length}件のツイートを追跡（48h〜14d）`);

  // バッチでツイート指標を取得（最大100件）
  const tweetIds = tweetEntries.map((e) => e.tweetId).slice(0, 100);
  let tweetsData = [];
  try {
    const response = await xClient.v2.tweets(tweetIds, {
      "tweet.fields": "public_metrics,created_at",
    });
    tweetsData = response.data || [];
  } catch (err) {
    console.warn(`[engagement] ツイート指標取得失敗: ${err.message}`);
    return;
  }

  // 指標をマップに変換
  const metricsMap = {};
  for (const tweet of tweetsData) {
    const m = tweet.public_metrics || {};
    metricsMap[tweet.id] = {
      likes: m.like_count || 0,
      retweets: m.retweet_count || 0,
      replies: m.reply_count || 0,
      quotes: m.quote_count || 0,
      bookmarks: m.bookmark_count || 0,
      impressions: m.impression_count || 0,
      fetchedAt: new Date().toISOString(),
    };
  }

  // post-history.json に engagements を追記
  const history = loadPostHistory();
  let historyUpdated = 0;
  for (const entry of tweetEntries) {
    const metrics = metricsMap[entry.tweetId];
    if (!metrics) continue;

    // post-history で該当するエントリを探す（text の先頭一致）
    const histEntry = history.entries.find(
      (h) => h.postedAt && h.text && entry.text.startsWith(h.text.slice(0, 30))
    );
    if (histEntry) {
      histEntry.engagements = metrics;
      histEntry.tweetId = entry.tweetId;
      historyUpdated++;
    }
  }
  if (historyUpdated > 0) {
    writeJson("post-history.json", history);
    console.log(`[engagement] post-history.json: ${historyUpdated}件のエンゲージメント更新`);
  }

  // x-engagement.json に全体サマリを保存
  const engagement = readJson("x-engagement.json") || {
    version: 1,
    lastUpdated: null,
    recentMetrics: [],
    topPosts: [],
    replyDigest: [],
  };

  engagement.lastUpdated = new Date().toISOString();

  // 直近の指標データ更新
  engagement.recentMetrics = tweetEntries
    .filter((e) => metricsMap[e.tweetId])
    .map((e) => ({
      tweetId: e.tweetId,
      postType: e.postType,
      textPreview: e.text,
      postedAt: e.postedAt,
      ...metricsMap[e.tweetId],
    }));

  // トップ投稿（ブクマ数順）
  engagement.topPosts = [...engagement.recentMetrics]
    .sort((a, b) => (b.bookmarks + b.likes) - (a.bookmarks + a.likes))
    .slice(0, 10);

  // リプライ取得（自分のアカウントへのメンション）
  try {
    const me = await xClient.v2.me();
    const userId = me.data.id;
    const mentions = await xClient.v2.userMentionTimeline(userId, {
      max_results: 20,
      "tweet.fields": "created_at,text,in_reply_to_user_id,conversation_id",
    });
    const mentionData = mentions.data?.data || [];
    engagement.replyDigest = mentionData
      .filter((m) => m.in_reply_to_user_id === userId) // 自分への直接リプライのみ
      .slice(0, 20)
      .map((m) => ({
        tweetId: m.id,
        text: m.text,
        createdAt: m.created_at,
        conversationId: m.conversation_id,
      }));
    console.log(`[engagement] リプライ: ${engagement.replyDigest.length}件取得`);
  } catch (err) {
    console.warn(`[engagement] リプライ取得失敗（スキップ）: ${err.message}`);
  }

  writeJson("x-engagement.json", engagement);
  console.log("[engagement] x-engagement.json を更新しました");
}

// ─── メイン ──────────────────────────────────────────

async function main() {
  await syncPostedStatus();
  await fetchEngagementData();
}

main().catch((err) => {
  console.error("エラー:", err.message);
  process.exit(1);
});
