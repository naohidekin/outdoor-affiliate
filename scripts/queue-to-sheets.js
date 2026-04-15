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
import { loadEnv, readJson, writeJson } from "../src/lib/x-agent-utils.mjs";

loadEnv();

const __dirname = path.dirname(fileURLToPath(import.meta.url));

// (loadEnv で .env.local 読み込み済み — 旧手動読み込みコード削除)
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

  // 「下書き管理」シートから全データを読み取り（U列=imageUrl まで）
  const res = await sheets.spreadsheets.values.get({
    spreadsheetId,
    range: `${DRAFT_SHEET}!A2:U`,
  });
  const rows = res.data.values || [];

  // 承認済みで投稿予定日が今日以前の行を特定
  const toQueue = [];
  for (let i = 0; i < rows.length; i++) {
    const row = rows[i];
    const status = row[6]; // G: status列
    const scheduledDate = row[7]; // H: scheduledDate列
    if (status === "approved" && scheduledDate <= today) {
      toQueue.push({
        rowIndex: i + 2, // +2 for header + 1-indexed
        id: row[0],
        type: row[1],
        text: row[2],
        url: row[4] || "",
        scheduledDate: row[7],
        selfReply: row[18] || "",  // S: selfReply列
        imageUrl: row[20] || "",   // U: imageUrl列
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

  // 「X投稿管理」に行を追加（I列=self_reply を含む）
  const queueRows = toQueue2.map((p) => [
    "ready",        // A: status
    p.type,         // B: post_type
    p.text,         // C: text
    p.imageUrl,     // D: image_url
    p.url,          // E: source_url
    p.scheduledDate, // F: scheduled_at
    "",             // G: posted_at
    "",             // H: post_url
    p.selfReply,    // I: self_reply
  ]);

  await sheets.spreadsheets.values.append({
    spreadsheetId,
    range: `${QUEUE_SHEET}!A:I`,
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

  // JSONキューにも同時書き込み（Sheets障害時のフォールバック用）
  const queueJson = readJson("post-queue.json") || { version: 1, queue: [] };
  for (const p of toQueue2) {
    queueJson.queue.push({
      status: "ready",
      type: p.type,
      text: p.text,
      url: p.url || "",
      selfReply: p.selfReply || "",
      scheduledDate: p.scheduledDate,
      queuedAt: new Date().toISOString(),
    });
  }
  writeJson("post-queue.json", queueJson);

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
