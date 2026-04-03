#!/usr/bin/env node

/**
 * 投稿済みステータス同期スクリプト
 * 「X投稿管理」シートで投稿済み（IFTTTが処理済み）の行を検出し、
 * 「下書き管理」シートのステータスを posted に更新する
 *
 * IFTTTが行を処理すると、その行はもう新しい行として検知されないため、
 * queuedのまま残っている行で、X投稿管理シートに存在するものを posted にする
 *
 * 使い方:
 *   node scripts/sync-posted-status.js
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

async function syncPostedStatus() {
  const spreadsheetId = process.env.X_SHEET_ID;
  if (!spreadsheetId) {
    console.error("X_SHEET_ID が設定されていません");
    process.exit(1);
  }

  const sheets = await getSheets();

  // 「X投稿管理」シートから投稿済みのテキストを取得
  const queueRes = await sheets.spreadsheets.values.get({
    spreadsheetId,
    range: `${QUEUE_SHEET}!A2:H`,
  });
  const queueRows = queueRes.data.values || [];

  // X投稿管理に存在するテキスト一覧（投稿済みとみなす）
  const postedTexts = new Set(
    queueRows.map((row) => (row[2] || "").trim().slice(0, 50))
  );

  if (postedTexts.size === 0) {
    console.log("X投稿管理シートに行がありません");
    return;
  }

  // 「下書き管理」シートから queued のものを探す
  const draftRes = await sheets.spreadsheets.values.get({
    spreadsheetId,
    range: `${DRAFT_SHEET}!A2:J`,
  });
  const draftRows = draftRes.data.values || [];

  let updatedCount = 0;
  for (let i = 0; i < draftRows.length; i++) {
    const row = draftRows[i];
    const status = row[6]; // status列
    const text = (row[2] || "").trim().slice(0, 50);

    if (status === "queued" && postedTexts.has(text)) {
      // ステータスを posted に更新、postedAtを設定
      const rowIndex = i + 2;
      await sheets.spreadsheets.values.update({
        spreadsheetId,
        range: `${DRAFT_SHEET}!G${rowIndex}:J${rowIndex}`,
        valueInputOption: "RAW",
        requestBody: {
          values: [["posted", row[7] || "", row[8] || "", new Date().toISOString()]],
        },
      });
      updatedCount++;
      console.log(`  posted: ${text}...`);
    }
  }

  if (updatedCount === 0) {
    console.log("更新対象のポストがありません");
  } else {
    console.log(`${updatedCount}件を posted に更新しました`);
  }
}

syncPostedStatus().catch((err) => {
  console.error("エラー:", err.message);
  process.exit(1);
});
