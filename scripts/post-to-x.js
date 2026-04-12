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

const __dirname = path.dirname(fileURLToPath(import.meta.url));

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

const QUEUE_SHEET = "X投稿管理";
const DRAFT_SHEET = "下書き管理";

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

async function postToX() {
  const spreadsheetId = process.env.X_SHEET_ID;
  if (!spreadsheetId) {
    console.error("X_SHEET_ID が設定されていません");
    process.exit(1);
  }

  const maxArg = process.argv.find((a) => a.startsWith("--max="));
  const maxCount = maxArg ? parseInt(maxArg.split("=")[1], 10) : 1;
  const dryRun = process.argv.includes("--dry-run");

  const sheets = await getSheets();
  const xClient = getXClient();

  // 「X投稿管理」シートから ready の行を取得
  const res = await sheets.spreadsheets.values.get({
    spreadsheetId,
    range: `${QUEUE_SHEET}!A2:H`,
  });
  const rows = res.data.values || [];

  const readyRows = [];
  for (let i = 0; i < rows.length; i++) {
    if (rows[i][0] === "ready") {
      readyRows.push({ rowIndex: i + 2, data: rows[i] });
    }
  }

  const targets = readyRows.slice(0, maxCount);

  if (targets.length === 0) {
    console.log("投稿対象の ready 行がありません");
    return;
  }

  console.log(`投稿対象: ${targets.length}件`);

  for (const target of targets) {
    const [, postType, text, imageUrl, sourceUrl, scheduledAt] = target.data;
    const preview = (text || "").slice(0, 60);
    console.log(`  [${postType}] ${preview}...`);

    if (dryRun) continue;

    try {
      const result = await xClient.v2.tweet(text);
      const tweetId = result.data.id;
      const postUrl = `https://x.com/camp_gear_lab/status/${tweetId}`;
      const postedAt = new Date().toISOString();

      // 「X投稿管理」シートを更新: status=posted, posted_at, post_url
      await sheets.spreadsheets.values.update({
        spreadsheetId,
        range: `${QUEUE_SHEET}!A${target.rowIndex}:H${target.rowIndex}`,
        valueInputOption: "RAW",
        requestBody: {
          values: [
            [
              "posted",
              postType,
              text,
              imageUrl || "",
              sourceUrl || "",
              scheduledAt || "",
              postedAt,
              postUrl,
            ],
          ],
        },
      });

      // 「下書き管理」シートも同期更新
      await syncDraftStatus(sheets, spreadsheetId, text, postedAt);

      console.log(`    → 投稿完了: ${postUrl}`);
    } catch (err) {
      console.error(`    → 投稿失敗: ${err.message}`);

      // エラーステータスを記録
      await sheets.spreadsheets.values.update({
        spreadsheetId,
        range: `${QUEUE_SHEET}!A${target.rowIndex}`,
        valueInputOption: "RAW",
        requestBody: { values: [["error"]] },
      });
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
