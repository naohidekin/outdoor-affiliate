#!/usr/bin/env node

/**
 * X (Twitter) 直接投稿スクリプト
 * 「X投稿管理」シートから status=ready の行を取得し、X API v2 で投稿する
 * IFTTT の代替として使用
 *
 * 必要な環境変数:
 *   GOOGLE_CREDENTIALS — サービスアカウントJSON（1行）
 *   X_SHEET_ID — スプレッドシートID
 *   X_API_KEY — X API Key (Consumer Key)
 *   X_API_SECRET — X API Key Secret
 *   X_ACCESS_TOKEN — X Access Token
 *   X_ACCESS_SECRET — X Access Token Secret
 *
 * 使い方:
 *   node scripts/post-to-x.js            # ready を1件投稿
 *   node scripts/post-to-x.js --max=3    # 最大3件投稿
 *   node scripts/post-to-x.js --dry-run  # 実行せずに対象を表示
 */

import { google } from "googleapis";
import { TwitterApi } from "twitter-api-v2";
import fs from "fs";
import path from "path";
import { fileURLToPath } from "url";
import https from "https";
import http from "http";
import {
  loadEnv,
  readJson,
  checkKillSwitch,
  loadPostHistory,
} from "../src/lib/x-agent-utils.mjs";

loadEnv();

const __dirname = path.dirname(fileURLToPath(import.meta.url));

const QUEUE_SHEET = "X投稿管理";
const DRAFT_SHEET = "下書き管理";

// ─── 安全装置（account-config.json から読み込み）───────

function loadSafetyConfig() {
  const config = readJson("account-config.json");
  return config?.safety || {
    dailyPostLimit: 3,
    minPostIntervalMinutes: 60,
    warmupSchedule: { week1: 2, week2: 3, week3: 4, "week4plus": 5 },
    accountStartDate: null,
  };
}

/**
 * ウォームアップスケジュールに基づく今日の投稿上限を計算。
 * アカウント開設（or 初投稿）からの経過週で段階的に増やす。
 */
function getEffectiveDailyLimit(safety, history) {
  const warmup = safety.warmupSchedule;
  if (!warmup) return safety.dailyPostLimit;

  // 開始日: account-config の accountStartDate、なければ初投稿日、なければ今日
  let startDate;
  if (safety.accountStartDate) {
    startDate = new Date(safety.accountStartDate);
  } else {
    const firstPost = history.entries.find((e) => e.postedAt);
    startDate = firstPost ? new Date(firstPost.postedAt) : new Date();
  }

  const now = new Date();
  const weeksSinceStart = Math.floor((now - startDate) / (7 * 24 * 60 * 60 * 1000)) + 1;

  let limit;
  if (weeksSinceStart <= 1) limit = warmup.week1 || 2;
  else if (weeksSinceStart <= 2) limit = warmup.week2 || 3;
  else if (weeksSinceStart <= 3) limit = warmup.week3 || 4;
  else limit = warmup["week4plus"] || safety.dailyPostLimit;

  console.log(`[poster] ウォームアップ: ${weeksSinceStart}週目 → 1日${limit}件上限`);
  return limit;
}

/**
 * 1日の投稿数と最低間隔をチェック。
 * @returns {{ allowed: boolean, reason: string }}
 */
function checkPostingSafety() {
  const safety = loadSafetyConfig();
  const history = loadPostHistory();
  const now = new Date();
  const todayStr = now.toISOString().slice(0, 10);

  // ウォームアップスケジュールに基づく動的上限
  const effectiveLimit = getEffectiveDailyLimit(safety, history);

  // 1日の投稿数チェック
  const todayPosts = history.entries.filter(
    (e) => e.postedAt && e.postedAt.startsWith(todayStr)
  );
  if (todayPosts.length >= effectiveLimit) {
    return { allowed: false, reason: `1日の投稿上限(${effectiveLimit}件, ウォームアップ適用)に到達` };
  }

  // 最低間隔チェック（最後の投稿から N 分以内なら拒否）
  const lastPosted = history.entries
    .filter((e) => e.postedAt)
    .sort((a, b) => new Date(b.postedAt) - new Date(a.postedAt))[0];

  if (lastPosted) {
    const elapsed = (now - new Date(lastPosted.postedAt)) / 60000; // 分
    if (elapsed < safety.minPostIntervalMinutes) {
      const remaining = Math.ceil(safety.minPostIntervalMinutes - elapsed);
      return { allowed: false, reason: `最低投稿間隔(${safety.minPostIntervalMinutes}分)未達。あと${remaining}分` };
    }
  }

  return { allowed: true, reason: "" };
}

// ─── 投稿タイプ別のセルフリプライ戦略 ─────────────────
const SELF_REPLY_TEMPLATES = {
  poll_question: [
    "みんなの意見もリプで教えて！",
    "理由も聞かせてもらえると嬉しい。",
    "結構割れると思うんだけど、どう？",
  ],
  failure_story: [
    "同じような経験ある人いる？笑",
    "これ、あるあるだと思うんだけど。",
  ],
  outdoor_tip: [
    "他にも「これ良いよ！」ってtipsあったら教えて。",
    "もっと良い方法知ってたらリプで教えて！",
  ],
  ai_dev_log: [
    "同じ体験した人いる？",
    "こういうの、他の人はどう解決してるんだろう。",
  ],
  parenting_outdoor: [
    "うちもこう！ってリプ待ってます。",
    "みんなの子供キャンプエピソードも聞きたい。",
  ],
};

async function getSheets() {
  const credentials = JSON.parse(process.env.GOOGLE_CREDENTIALS);
  const auth = new google.auth.GoogleAuth({
    credentials,
    scopes: ["https://www.googleapis.com/auth/spreadsheets"],
  });
  return google.sheets({ version: "v4", auth });
}

function getXClient() {
  const { X_API_KEY, X_API_SECRET, X_ACCESS_TOKEN, X_ACCESS_SECRET } =
    process.env;
  if (!X_API_KEY || !X_API_SECRET || !X_ACCESS_TOKEN || !X_ACCESS_SECRET) {
    console.error(
      "X API キーが設定されていません（X_API_KEY, X_API_SECRET, X_ACCESS_TOKEN, X_ACCESS_SECRET）"
    );
    process.exit(1);
  }
  return new TwitterApi({
    appKey: X_API_KEY,
    appSecret: X_API_SECRET,
    accessToken: X_ACCESS_TOKEN,
    accessSecret: X_ACCESS_SECRET,
  });
}

/**
 * URL から画像を Buffer としてダウンロードする（リダイレクト1段対応）
 */
function downloadImageBuffer(url) {
  return new Promise((resolve, reject) => {
    const client = url.startsWith("https") ? https : http;
    client.get(url, (res) => {
      if (res.statusCode === 301 || res.statusCode === 302) {
        return downloadImageBuffer(res.headers.location).then(resolve, reject);
      }
      if (res.statusCode !== 200) {
        return reject(new Error(`画像取得失敗 HTTP ${res.statusCode}: ${url}`));
      }
      const chunks = [];
      res.on("data", (c) => chunks.push(c));
      res.on("end", () => resolve(Buffer.concat(chunks)));
      res.on("error", reject);
    }).on("error", reject);
  });
}

/**
 * imageUrl を X にアップロードして mediaId を返す。
 * 失敗した場合は null を返す（投稿自体は続行）。
 */
async function uploadImageToX(xClient, imageUrl) {
  if (!imageUrl || !imageUrl.trim()) return null;
  try {
    const buf = await downloadImageBuffer(imageUrl.trim());
    // MIME type を URL から推定（OG画像 /opengraph-image は PNG）
    const mime = (imageUrl.includes(".png") || imageUrl.includes("opengraph-image")) ? "image/png"
      : imageUrl.includes(".gif") ? "image/gif"
      : "image/jpeg";
    const mediaId = await xClient.v1.uploadMedia(buf, { mimeType: mime });
    console.log(`    → 画像アップロード完了: mediaId=${mediaId}`);
    return mediaId;
  } catch (err) {
    console.warn(`    → 画像アップロード失敗（テキストのみで投稿）: ${err.message}`);
    return null;
  }
}

/**
 * 投稿タイプに応じたセルフリプライテンプレートからランダムに選択。
 * シートにselfReplyが保存されていない場合のフォールバック。
 */
function pickSelfReply(postType) {
  const templates = SELF_REPLY_TEMPLATES[postType];
  if (!templates || templates.length === 0) return null;
  return templates[Math.floor(Math.random() * templates.length)];
}

async function postToX() {
  // KILL SWITCH チェック
  const ks = checkKillSwitch();
  if (ks.killed) {
    console.error(`[poster] KILL SWITCH 有効: ${ks.reason}`);
    process.exit(1);
  }

  const spreadsheetId = process.env.X_SHEET_ID;
  if (!spreadsheetId) {
    console.error("X_SHEET_ID が設定されていません");
    process.exit(1);
  }

  const maxArg = process.argv.find((a) => a.startsWith("--max="));
  const maxCount = maxArg ? parseInt(maxArg.split("=")[1], 10) : 1;
  const dryRun = process.argv.includes("--dry-run");

  // 安全装置チェック（dry-run 時はスキップ）
  if (!dryRun) {
    const safetyCheck = checkPostingSafety();
    if (!safetyCheck.allowed) {
      console.log(`[poster] 安全装置: ${safetyCheck.reason}`);
      return;
    }
  }

  let sheets;
  try {
    sheets = await getSheets();
  } catch (err) {
    console.warn(`[poster] Sheets接続失敗: ${err.message}`);
    sheets = null;
  }
  const xClient = getXClient();

  // 「X投稿管理」シートから ready の行を取得 → 失敗時はJSONフォールバック
  let readyRows = [];
  let useJsonFallback = false;

  if (sheets) {
    try {
      const res = await sheets.spreadsheets.values.get({
        spreadsheetId,
        range: `${QUEUE_SHEET}!A2:I`,
      });
      const rows = res.data.values || [];
      for (let i = 0; i < rows.length; i++) {
        if (rows[i][0] === "ready") {
          readyRows.push({ rowIndex: i + 2, data: rows[i], source: "sheets" });
        }
      }
    } catch (err) {
      console.warn(`[poster] Sheets読み取り失敗: ${err.message}。JSONフォールバック使用`);
      sheets = null;
    }
  }

  // Sheets失敗時: post-queue.json からready行を取得
  if (!sheets || readyRows.length === 0) {
    const queueJson = readJson("post-queue.json");
    if (queueJson?.queue) {
      const jsonReady = queueJson.queue.filter((q) => q.status === "ready");
      for (let i = 0; i < jsonReady.length; i++) {
        const q = jsonReady[i];
        readyRows.push({
          rowIndex: -1, // Sheets行番号なし
          data: ["ready", q.type, q.text, "", q.url || "", q.scheduledDate || "", "", "", q.selfReply || ""],
          source: "json",
          jsonIndex: queueJson.queue.indexOf(q),
        });
      }
      if (jsonReady.length > 0) {
        useJsonFallback = true;
        console.log(`[poster] JSONフォールバック: ${jsonReady.length}件のready行`);
      }
    }
  }

  // 安全装置: ウォームアップ考慮の残り投稿枠
  const safety = loadSafetyConfig();
  const history = loadPostHistory();
  const todayStr = new Date().toISOString().slice(0, 10);
  const todayCount = history.entries.filter((e) => e.postedAt?.startsWith(todayStr)).length;
  const effectiveLimit = getEffectiveDailyLimit(safety, history);
  const remaining = Math.max(0, effectiveLimit - todayCount);
  const effectiveMax = Math.min(maxCount, remaining);

  const targets = readyRows.slice(0, effectiveMax);

  if (targets.length === 0) {
    console.log("投稿対象の ready 行がありません（または1日上限到達）");
    return;
  }

  console.log(`投稿対象: ${targets.length}件 (本日残枠: ${remaining}件)`);

  for (const target of targets) {
    const [, postType, rawText, imageUrl, sourceUrl, scheduledAt, , , selfReply] = target.data;
    // 本文からURL全除去（URLは必ずセルフリプライのみ — 本文掲載禁止）
    const text = (rawText || "")
      .replace(/https?:\/\/\S+/g, "")
      .replace(/\n{3,}/g, "\n\n")
      .trim();
    const preview = text.slice(0, 60);
    console.log(`  [${postType}] ${preview}...`);

    if (dryRun) continue;

    try {
      let tweetId;
      let postUrl;
      const postedAt = new Date().toISOString();

      // ─── スレッド投稿（gear_thread） ─────────────────
      if (text && text.startsWith("[THREAD]")) {
        const tweetsJson = text.replace(/^\[THREAD\]\s*/, "");
        let tweets;
        try {
          tweets = JSON.parse(tweetsJson);
        } catch {
          console.error(`    → スレッドJSON解析失敗: ${tweetsJson.slice(0, 100)}`);
          throw new Error("スレッドJSON解析失敗");
        }

        // URL 除去（スレッド各ツイートにも適用 — 本文掲載禁止）
        const sanitize = (t) =>
          (t || "").replace(/https?:\/\/\S+/g, "").replace(/\n{3,}/g, "\n\n").trim();
        tweets = tweets.map(sanitize);

        // sourceUrl がある場合は最後のツイートにリプ欄誘導を追記
        if (sourceUrl && sourceUrl.trim() && tweets.length > 0) {
          tweets[tweets.length - 1] = `${tweets[tweets.length - 1]}\n\n詳細はリプ欄へ。`;
        }

        // 最初のツイートを投稿
        const firstResult = await xClient.v2.tweet(tweets[0]);
        tweetId = firstResult.data.id;
        postUrl = `https://x.com/camp_gear_lab/status/${tweetId}`;
        console.log(`    → スレッド開始: ${postUrl}`);

        // 2番目以降を連鎖リプライ
        let prevId = tweetId;
        for (let i = 1; i < tweets.length; i++) {
          try {
            const replyResult = await xClient.v2.tweet(tweets[i], {
              reply: { in_reply_to_tweet_id: prevId },
            });
            prevId = replyResult.data.id;
            console.log(`    → スレッド ${i + 1}/${tweets.length}`);
          } catch (threadErr) {
            console.warn(`    → スレッド ${i + 1} 投稿失敗（続行）: ${threadErr.message}`);
          }
        }

        // スレッド末尾にURLセルフリプライ（URLのみ — 最後のツイートに「詳細はリプ欄へ。」追記済み）
        if (sourceUrl && sourceUrl.trim()) {
          try {
            await xClient.v2.tweet(sourceUrl, {
              reply: { in_reply_to_tweet_id: prevId },
            });
            console.log(`    → スレッド末尾URLリプライ: ${sourceUrl.slice(0, 60)}`);
          } catch (replyErr) {
            console.warn(`    → URLリプライ失敗: ${replyErr.message}`);
          }
        }

      // ─── 通常投稿（シングルツイート） ──────────────────
      } else {
        // sourceUrl がある場合は本文末尾にリプ欄誘導を追記
        const mainText = sourceUrl && sourceUrl.trim()
          ? `${text}\n\n詳細はリプ欄へ。`
          : text;

        // 画像添付（imageUrl がある場合はアップロードして mediaId を取得）
        const mediaId = await uploadImageToX(xClient, imageUrl);
        const tweetPayload = mediaId
          ? { media: { media_ids: [mediaId] } }
          : {};
        const result = await xClient.v2.tweet(mainText, tweetPayload);
        tweetId = result.data.id;
        postUrl = `https://x.com/camp_gear_lab/status/${tweetId}`;

        // セルフリプライ投稿（コメント誘導 / 続き）
        const replyText = selfReply?.trim() || pickSelfReply(postType);
        if (replyText) {
          try {
            await xClient.v2.tweet(replyText, {
              reply: { in_reply_to_tweet_id: tweetId },
            });
            console.log(`    → セルフリプライ: ${replyText.slice(0, 40)}`);
          } catch (replyErr) {
            console.warn(`    → セルフリプライ失敗: ${replyErr.message}`);
          }
        }

        // URL セルフリプライ（URLのみ — 本文に「詳細はリプ欄へ。」を追記済み）
        if (sourceUrl && sourceUrl.trim()) {
          try {
            await xClient.v2.tweet(sourceUrl, {
              reply: { in_reply_to_tweet_id: tweetId },
            });
            console.log(`    → URLセルフリプライ: ${sourceUrl.slice(0, 60)}`);
          } catch (replyErr) {
            console.warn(`    → URLリプライ失敗（メイン投稿は成功）: ${replyErr.message}`);
          }
        }
      }

      // Sheets更新（接続可能な場合のみ）
      if (sheets && target.rowIndex > 0) {
        try {
          await sheets.spreadsheets.values.update({
            spreadsheetId,
            range: `${QUEUE_SHEET}!A${target.rowIndex}:I${target.rowIndex}`,
            valueInputOption: "RAW",
            requestBody: {
              values: [[
                "posted", postType, text, imageUrl || "", sourceUrl || "",
                scheduledAt || "", postedAt, postUrl, selfReply || "",
              ]],
            },
          });
          await syncDraftStatus(sheets, spreadsheetId, text, postedAt);
        } catch (sheetErr) {
          console.warn(`    → Sheets更新失敗（投稿自体は成功）: ${sheetErr.message}`);
        }
      }

      // JSONキュー更新（常に実行 — Sheets障害時でもデータ保全）
      const queueJson = readJson("post-queue.json") || { version: 1, queue: [] };
      const qEntry = queueJson.queue.find((q) => q.text === text && q.status === "ready");
      if (qEntry) {
        qEntry.status = "posted";
        qEntry.postedAt = postedAt;
        qEntry.postUrl = postUrl;
      }
      const { writeJson: wj } = await import("../src/lib/x-agent-utils.mjs");
      wj("post-queue.json", queueJson);

      // post-history.json の postedAt を更新（安全装置の投稿間隔・日次上限に使用）
      const postHistory = loadPostHistory();
      const histEntry = postHistory.entries.find((e) => e.text === text || e.text?.trim() === text?.trim());
      if (histEntry) {
        histEntry.postedAt = postedAt;
        wj("post-history.json", postHistory);
      }

      console.log(`    → 投稿完了: ${postUrl}`);
    } catch (err) {
      console.error(`    → 投稿失敗: ${err.message}`);

      // エラーステータスを記録（Sheets + JSON両方）
      if (sheets && target.rowIndex > 0) {
        try {
          await sheets.spreadsheets.values.update({
            spreadsheetId,
            range: `${QUEUE_SHEET}!A${target.rowIndex}`,
            valueInputOption: "RAW",
            requestBody: { values: [["error"]] },
          });
        } catch { /* Sheets障害時は無視 */ }
      }
    }
  }

  if (dryRun) {
    console.log("\n--- DRY RUN: 投稿は行いません ---");
  }
}

async function syncDraftStatus(sheets, spreadsheetId, text, postedAt) {
  const res = await sheets.spreadsheets.values.get({
    spreadsheetId,
    range: `${DRAFT_SHEET}!A2:J`,
  });
  const rows = res.data.values || [];
  const trimmedText = text?.trim();

  for (let i = 0; i < rows.length; i++) {
    const row = rows[i];
    if (row[6] === "queued" && row[2]?.trim() === trimmedText) {
      const rowIndex = i + 2;
      await sheets.spreadsheets.values.update({
        spreadsheetId,
        range: `${DRAFT_SHEET}!G${rowIndex}:J${rowIndex}`,
        valueInputOption: "RAW",
        requestBody: {
          values: [["posted", row[7] || "", row[8] || "", postedAt]],
        },
      });
      break;
    }
  }
}

postToX().catch((err) => {
  console.error("エラー:", err.message);
  process.exit(1);
});
