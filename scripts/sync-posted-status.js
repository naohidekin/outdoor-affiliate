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
  for (let i = 0; i < draftRows.length; i++) {
    const row = draftRows[i];
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
      console.log(`  更新: ${text.slice(0, 40)}...`);
    }
  }

  console.log(`${updated}件のポストをpostedに更新しました`);
}

syncPostedStatus().catch((err) => {
  console.error("エラー:", err.message);
  process.exit(1);
});
