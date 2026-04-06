#!/usr/bin/env node

/**
 * 「ケンタ」→「ギア男」一括置換スクリプト
 * - data/x-posts.json をスキャン
 * - Google Sheets「下書き管理」「X投稿管理」をスキャン
 * - --apply フラグなしならドライラン（検出のみ）
 * - --apply フラグありで実置換
 *
 * 使い方:
 *   node scripts/replace-kenta.js          # ドライラン
 *   node scripts/replace-kenta.js --apply  # 実置換
 *
 * 必要な環境変数（Sheets スキャン時）:
 *   GOOGLE_CREDENTIALS / X_SHEET_ID
 */

import { google } from "googleapis";
import fs from "fs";
import path from "path";
import { fileURLToPath } from "url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const ROOT = path.join(__dirname, "..");
const APPLY = process.argv.includes("--apply");
const FROM = "ケンタ";
const TO = "ギア男";

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

function scanJson(filename) {
  const filePath = path.join(ROOT, "data", filename);
  if (!fs.existsSync(filePath)) {
    console.log(`  (skip) ${filename} 無し`);
    return 0;
  }
  const text = fs.readFileSync(filePath, "utf-8");
  const matches = (text.match(new RegExp(FROM, "g")) || []).length;
  if (matches === 0) {
    console.log(`  ✓ ${filename}: 0件`);
    return 0;
  }
  console.log(`  ⚠ ${filename}: ${matches}件 検出`);
  if (APPLY) {
    fs.writeFileSync(filePath, text.replaceAll(FROM, TO));
    console.log(`    → 置換しました`);
  }
  return matches;
}

async function scanSheets() {
  if (!process.env.X_SHEET_ID || !process.env.GOOGLE_CREDENTIALS) {
    console.log("  (skip) GOOGLE_CREDENTIALS / X_SHEET_ID 未設定");
    return 0;
  }
  const credentials = JSON.parse(process.env.GOOGLE_CREDENTIALS);
  const auth = new google.auth.GoogleAuth({
    credentials,
    scopes: ["https://www.googleapis.com/auth/spreadsheets"],
  });
  const sheets = google.sheets({ version: "v4", auth });
  const spreadsheetId = process.env.X_SHEET_ID;

  const meta = await sheets.spreadsheets.get({ spreadsheetId });
  const titles = (meta.data.sheets || [])
    .map((s) => s.properties?.title)
    .filter(Boolean);

  let totalMatches = 0;
  for (const title of titles) {
    const res = await sheets.spreadsheets.values.get({
      spreadsheetId,
      range: `${title}!A:Z`,
    });
    const rows = res.data.values || [];
    let sheetMatches = 0;
    const updated = rows.map((row) =>
      row.map((cell) => {
        if (typeof cell !== "string") return cell;
        const m = (cell.match(new RegExp(FROM, "g")) || []).length;
        if (m > 0) sheetMatches += m;
        return cell.replaceAll(FROM, TO);
      })
    );
    if (sheetMatches === 0) {
      console.log(`  ✓ シート「${title}」: 0件`);
      continue;
    }
    console.log(`  ⚠ シート「${title}」: ${sheetMatches}件 検出`);
    totalMatches += sheetMatches;
    if (APPLY && rows.length > 0) {
      await sheets.spreadsheets.values.update({
        spreadsheetId,
        range: `${title}!A1`,
        valueInputOption: "RAW",
        requestBody: { values: updated },
      });
      console.log(`    → 置換しました`);
    }
  }
  return totalMatches;
}

async function main() {
  console.log(`\n🔍 「${FROM}」→「${TO}」 ${APPLY ? "実置換" : "ドライラン"}\n`);

  console.log("== JSON ==");
  const j1 = scanJson("x-posts.json");

  console.log("\n== Google Sheets ==");
  const s1 = await scanSheets();

  const total = j1 + s1;
  console.log(`\n合計: ${total}件 ${APPLY ? "置換完了" : "検出"}`);
  if (!APPLY && total > 0) {
    console.log("実置換は --apply を付けて再実行してください");
  }
}

main().catch((err) => {
  console.error("エラー:", err.message);
  process.exit(1);
});
