#!/usr/bin/env node

/**
 * Threads 手動投稿ドラフト表示スクリプト
 *
 * 「下書き管理」シートから本日以前の queued/posted 投稿で
 * threads_status（V列）が空のものを取得し、
 * Threads 用にフォーマットしてターミナルに表示する。
 *
 * 使い方:
 *   node scripts/threads-daily-draft.js          # 本日分を表示
 *   node scripts/threads-daily-draft.js --max=3  # 最大3件表示
 */

import { google } from "googleapis";
import { loadEnv } from "../src/lib/x-agent-utils.mjs";

loadEnv();

const DRAFT_SHEET = "下書き管理";
const SITE_URL = "https://camp-gear-lab.com";

function parseArgs() {
  const args = process.argv.slice(2);
  return {
    max: parseInt(args.find((a) => a.startsWith("--max="))?.split("=")[1] || "3"),
  };
}

async function getSheets() {
  const credentials = JSON.parse(process.env.GOOGLE_CREDENTIALS);
  const auth = new google.auth.GoogleAuth({
    credentials,
    scopes: ["https://www.googleapis.com/auth/spreadsheets.readonly"],
  });
  return google.sheets({ version: "v4", auth });
}

/**
 * X テキストを Threads 用に調整
 * - 500文字まで拡張可能（X は 280 文字）
 * - URL は末尾に追加（Threads はリンクプレビューなし）
 */
function formatForThreads(text, sourceUrl) {
  let t = (text || "").trim();

  // [THREAD] プレフィックスを除去
  t = t.replace(/^\[THREAD\]\s*/, "");

  // sourceUrl を末尾に追加（未含有 & 500文字以内）
  if (sourceUrl && !t.includes(sourceUrl)) {
    const withUrl = `${t}\n\n${sourceUrl}`;
    if (withUrl.length <= 500) t = withUrl;
  }

  return t;
}

async function main() {
  const opts = parseArgs();

  if (!process.env.X_SHEET_ID || !process.env.GOOGLE_CREDENTIALS) {
    console.error("X_SHEET_ID / GOOGLE_CREDENTIALS が未設定");
    process.exit(1);
  }

  const sheets = await getSheets();
  const spreadsheetId = process.env.X_SHEET_ID;
  const today = new Date().toISOString().slice(0, 10);

  const res = await sheets.spreadsheets.values.get({
    spreadsheetId,
    range: `${DRAFT_SHEET}!A2:W`,
  });
  const rows = res.data.values || [];

  // queued または posted かつ threads_status（V=index21）が空
  const candidates = rows
    .map((row, i) => ({ row, rowIndex: i + 2 }))
    .filter(({ row }) => {
      const status = row[6];         // G: status
      const scheduledDate = row[7];  // H: scheduledDate
      const threadsStatus = row[21]; // V: threads_status
      return (
        (status === "queued" || status === "posted") &&
        !threadsStatus &&
        (!scheduledDate || scheduledDate <= today)
      );
    })
    .slice(0, opts.max);

  if (candidates.length === 0) {
    console.log("本日の Threads 投稿候補なし（queued/posted かつ threads未投稿の行がない）");
    return;
  }

  console.log("═".repeat(60));
  console.log(`  Threads 手動投稿ドラフト  ${today}  (${candidates.length}件)`);
  console.log("═".repeat(60));

  candidates.forEach(({ row, rowIndex }, idx) => {
    const text = row[2] || "";
    const sourceUrl = row[4] || "";
    const type = row[1] || "";
    const threadsText = formatForThreads(text, sourceUrl);

    console.log(`\n【${idx + 1}/${candidates.length}】 行${rowIndex} type:${type}`);
    console.log("─".repeat(60));
    console.log(threadsText);
    console.log("─".repeat(60));
    console.log(`文字数: ${threadsText.length}/500`);
  });

  console.log("\n投稿後は下書き管理シートの V列に「posted」と入力してください");
  console.log(`シート: https://docs.google.com/spreadsheets/d/${spreadsheetId}`);
}

main().catch((err) => {
  console.error("エラー:", err.message);
  process.exit(1);
});
