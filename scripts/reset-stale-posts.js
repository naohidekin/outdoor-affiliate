#!/usr/bin/env node

/**
 * 古い滞留投稿のリセットスクリプト
 * scheduledDate が指定日数以上前かつ未投稿の行を draft に戻し、scheduledDate をクリアする
 *
 * 使い方:
 *   node scripts/reset-stale-posts.js            # デフォルト: 7日以上前
 *   node scripts/reset-stale-posts.js --days=14   # 14日以上前
 *   node scripts/reset-stale-posts.js --dry-run    # 実行せずに対象を表示
 */

import { google } from "googleapis";
import fs from "fs";
import path from "path";
import { fileURLToPath } from "url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));

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

async function getSheets() {
  const credentials = JSON.parse(process.env.GOOGLE_CREDENTIALS);
  const auth = new google.auth.GoogleAuth({
    credentials,
    scopes: ["https://www.googleapis.com/auth/spreadsheets"],
  });
  return google.sheets({ version: "v4", auth });
}

async function resetStalePosts() {
  const spreadsheetId = process.env.X_SHEET_ID;
  if (!spreadsheetId) {
    console.error("X_SHEET_ID が設定されていません");
    process.exit(1);
  }

  const daysArg = process.argv.find((a) => a.startsWith("--days="));
  const days = daysArg ? parseInt(daysArg.split("=")[1], 10) : 7;
  const dryRun = process.argv.includes("--dry-run");

  const cutoff = new Date();
  cutoff.setDate(cutoff.getDate() - days);
  const cutoffStr = [
    cutoff.getFullYear(),
    String(cutoff.getMonth() + 1).padStart(2, "0"),
    String(cutoff.getDate()).padStart(2, "0"),
  ].join("-");

  console.log(`基準日: ${cutoffStr}（${days}日以上前の未投稿をリセット）`);
  if (dryRun) console.log("--- DRY RUN モード ---");

  const sheets = await getSheets();
  const res = await sheets.spreadsheets.values.get({
    spreadsheetId,
    range: `${DRAFT_SHEET}!A2:N`,
  });
  const rows = res.data.values || [];

  const targets = [];
  for (let i = 0; i < rows.length; i++) {
    const row = rows[i];
    const status = row[6];
    const scheduledDate = row[7];
    if (
      scheduledDate &&
      scheduledDate < cutoffStr &&
      status !== "posted"
    ) {
      targets.push({
        rowIndex: i + 2,
        id: row[0],
        type: row[1],
        text: (row[2] || "").slice(0, 50),
        status,
        scheduledDate,
      });
    }
  }

  if (targets.length === 0) {
    console.log("リセット対象の投稿はありません");
    return;
  }

  console.log(`\nリセット対象: ${targets.length}件`);
  for (const t of targets) {
    console.log(
      `  [${t.scheduledDate}] ${t.status} → draft | ${t.type} | ${t.text}...`
    );
  }

  if (dryRun) {
    console.log("\n--- DRY RUN: 変更は行いません ---");
    return;
  }

  for (const t of targets) {
    await sheets.spreadsheets.values.update({
      spreadsheetId,
      range: `${DRAFT_SHEET}!G${t.rowIndex}:H${t.rowIndex}`,
      valueInputOption: "RAW",
      requestBody: { values: [["draft", ""]] },
    });
  }

  console.log(`\n${targets.length}件をdraftにリセットし、scheduledDateをクリアしました`);
}

resetStalePosts().catch((err) => {
  console.error("エラー:", err.message);
  process.exit(1);
});
