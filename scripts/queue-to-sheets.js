#!/usr/bin/env node

/**
 * Google Sheetsキュー投入スクリプト
 * 「下書き管理」シートから承認済みのX投稿を「X投稿管理」シートに書き込み、
 * IFTTTが投稿する
 *
 * 必要な環境変数:
 *   GOOGLE_CREDENTIALS — サービスアカウントJSON（1行）
 *   X_SHEET_ID — スプレッドシートID
 *
 * 使い方:
 *   node scripts/queue-to-sheets.js
 *   node scripts/queue-to-sheets.js --max=1 --random-delay=59
 */

import { google } from "googleapis";
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

function randomDelay(maxMinutes) {
  const minutes = Math.floor(Math.random() * maxMinutes);
  console.log(`ランダム遅延: ${minutes}分待機...`);
  return new Promise((resolve) => setTimeout(resolve, minutes * 60 * 1000));
}

async function queueToSheets() {
  const spreadsheetId = process.env.X_SHEET_ID;
  if (!spreadsheetId) {
    console.error("X_SHEET_ID が設定されていません");
    process.exit(1);
  }
  if (!process.env.GOOGLE_CREDENTIALS) {
    console.error("GOOGLE_CREDENTIALS が設定されていません");
    process.exit(1);
  }

  const sheets = await getSheets();
  const today = new Date().toISOString().slice(0, 10);

  // 「下書き管理」シートから全データを読み取り（K=scheduledTime, L=imageUrl 含む）
  const res = await sheets.spreadsheets.values.get({
    spreadsheetId,
    range: `${DRAFT_SHEET}!A2:N`,
  });
  const rows = res.data.values || [];

  // 承認済みで投稿予定日が今日以前の行を特定
  const toQueue = [];
  for (let i = 0; i < rows.length; i++) {
    const row = rows[i];
    const status = row[6]; // status列
    const scheduledDate = row[7]; // scheduledDate列
    if (status === "approved" && scheduledDate <= today) {
      toQueue.push({
        rowIndex: i + 2, // +2 for header + 1-indexed
        id: row[0],
        type: row[1],
        text: row[2],
        url: row[4] || "",
        scheduledDate: row[7],
        scheduledTime: row[10] || "", // K列
        imageUrl: row[11] || "",      // L列
      });
    }
  }

  // --max=N で投入件数を制限
  const maxArg = process.argv.find((a) => a.startsWith("--max="));
  const maxCount = maxArg ? parseInt(maxArg.split("=")[1], 10) : toQueue.length;
  const limited = toQueue.slice(0, maxCount);

  if (limited.length === 0) {
    console.log("キュー投入対象のポストがありません");
    return;
  }

  // --random-delay=N で0〜N分のランダム遅延
  const delayArg = process.argv.find((a) => a.startsWith("--random-delay="));
  if (delayArg) {
    const maxMin = parseInt(delayArg.split("=")[1], 10);
    await randomDelay(maxMin);
  }

  const toQueue2 = limited;
  console.log(`${toQueue2.length}件のポストをSheetsに投入します...`);

  // 「X投稿管理」シートにヘッダーがなければ作成
  try {
    const existing = await sheets.spreadsheets.values.get({
      spreadsheetId,
      range: `${QUEUE_SHEET}!A1:H1`,
    });
    if (!existing.data.values || existing.data.values.length === 0) {
      await sheets.spreadsheets.values.update({
        spreadsheetId,
        range: `${QUEUE_SHEET}!A1:H1`,
        valueInputOption: "RAW",
        requestBody: {
          values: [
            [
              "status",
              "post_type",
              "text",
              "image_url",
              "source_url",
              "scheduled_at",
              "posted_at",
              "post_url",
            ],
          ],
        },
      });
    }
  } catch (err) {
    if (err.code === 400 || err.message?.includes("Unable to parse range")) {
      console.log(`シート「${QUEUE_SHEET}」を作成します...`);
      await sheets.spreadsheets.batchUpdate({
        spreadsheetId,
        requestBody: {
          requests: [
            { addSheet: { properties: { title: QUEUE_SHEET } } },
          ],
        },
      });
      await sheets.spreadsheets.values.update({
        spreadsheetId,
        range: `${QUEUE_SHEET}!A1:H1`,
        valueInputOption: "RAW",
        requestBody: {
          values: [
            [
              "status",
              "post_type",
              "text",
              "image_url",
              "source_url",
              "scheduled_at",
              "posted_at",
              "post_url",
            ],
          ],
        },
      });
    } else {
      throw err;
    }
  }

  // 「X投稿管理」に行を追加
  // scheduled_at は scheduledTime があれば "YYYY-MM-DD HH:MM"、なければ日付のみ
  // → 当面 IFTTT は date のみ運用、cron発火(Phase5)で時刻スロット対応
  const queueRows = toQueue2.map((p) => [
    "ready",
    p.type,
    p.text,
    p.imageUrl || "",
    p.url,
    p.scheduledTime ? `${p.scheduledDate} ${p.scheduledTime}` : p.scheduledDate,
    "",
    "",
  ]);

  await sheets.spreadsheets.values.append({
    spreadsheetId,
    range: `${QUEUE_SHEET}!A:H`,
    valueInputOption: "RAW",
    requestBody: { values: queueRows },
  });

  // 「下書き管理」シートのステータスを queued に更新
  for (const p of toQueue2) {
    await sheets.spreadsheets.values.update({
      spreadsheetId,
      range: `${DRAFT_SHEET}!G${p.rowIndex}`,
      valueInputOption: "RAW",
      requestBody: { values: [["queued"]] },
    });
  }

  console.log(
    `${toQueue2.length}件をSheetsに投入し、ステータスをqueuedに更新しました`
  );
  for (const p of toQueue2) {
    console.log(`  [${p.scheduledDate}] ${p.type}: ${p.text.slice(0, 40)}...`);
  }
}

queueToSheets().catch((err) => {
  console.error("エラー:", err.message);
  process.exit(1);
});
