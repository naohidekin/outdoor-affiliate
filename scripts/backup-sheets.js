#!/usr/bin/env node

/**
 * Google Sheets バックアップスクリプト
 * X_SHEET_ID で指定されたスプレッドシートの全シートを JSON で
 * data/backups/sheets-YYYYMMDD-HHMMSS.json に保存する
 *
 * 使い方:
 *   node scripts/backup-sheets.js
 *
 * 必要な環境変数:
 *   GOOGLE_CREDENTIALS — サービスアカウントJSON（1行）
 *   X_SHEET_ID         — スプレッドシートID
 */

import { google } from "googleapis";
import fs from "fs";
import path from "path";
import { fileURLToPath } from "url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const ROOT = path.join(__dirname, "..");

// .env.local を手動読み込み
const envPath = path.join(ROOT, ".env.local");
if (fs.existsSync(envPath)) {
  const envContent = fs.readFileSync(envPath, "utf-8");
  for (const line of envContent.split("\n")) {
    const m = line.match(/^([^#=]+)=(.*)$/);
    if (m && !process.env[m[1].trim()]) {
      process.env[m[1].trim()] = m[2].trim();
    }
  }
}

async function main() {
  const spreadsheetId = process.env.X_SHEET_ID;
  if (!spreadsheetId) {
    console.error("X_SHEET_ID が設定されていません");
    process.exit(1);
  }
  if (!process.env.GOOGLE_CREDENTIALS) {
    console.error("GOOGLE_CREDENTIALS が設定されていません");
    process.exit(1);
  }

  const credentials = JSON.parse(process.env.GOOGLE_CREDENTIALS);
  const auth = new google.auth.GoogleAuth({
    credentials,
    scopes: ["https://www.googleapis.com/auth/spreadsheets.readonly"],
  });
  const sheets = google.sheets({ version: "v4", auth });

  console.log("📥 シート構成を取得中...");
  const meta = await sheets.spreadsheets.get({ spreadsheetId });
  const titles = (meta.data.sheets || [])
    .map((s) => s.properties?.title)
    .filter(Boolean);

  console.log(`  対象シート: ${titles.join(", ")}`);

  const backup = {
    spreadsheetId,
    backedUpAt: new Date().toISOString(),
    title: meta.data.properties?.title || null,
    sheets: {},
  };

  for (const title of titles) {
    const res = await sheets.spreadsheets.values.get({
      spreadsheetId,
      range: `${title}!A:Z`,
    });
    backup.sheets[title] = res.data.values || [];
    console.log(`  ✓ ${title}: ${backup.sheets[title].length} 行`);
  }

  const backupDir = path.join(ROOT, "data", "backups");
  fs.mkdirSync(backupDir, { recursive: true });
  const stamp = new Date()
    .toISOString()
    .replace(/[-:T]/g, "")
    .slice(0, 15);
  const outPath = path.join(backupDir, `sheets-${stamp}.json`);
  fs.writeFileSync(outPath, JSON.stringify(backup, null, 2));

  console.log(`\n✅ バックアップ完了: ${path.relative(ROOT, outPath)}`);
}

main().catch((err) => {
  console.error("エラー:", err.message);
  process.exit(1);
});
