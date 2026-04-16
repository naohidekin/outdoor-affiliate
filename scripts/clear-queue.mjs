#!/usr/bin/env node
/**
 * 下書き管理シートの queued ポストを全て rejected に変更する
 * 再生成前のクリーンアップ用
 */
import { google } from "googleapis";
import { loadEnv } from "../src/lib/x-agent-utils.mjs";

loadEnv();

const DRAFT_SHEET = "下書き管理";

async function main() {
  const credentials = JSON.parse(process.env.GOOGLE_CREDENTIALS);
  const auth = new google.auth.GoogleAuth({
    credentials,
    scopes: ["https://www.googleapis.com/auth/spreadsheets"],
  });
  const sheets = google.sheets({ version: "v4", auth });
  const spreadsheetId = process.env.X_SHEET_ID;

  const res = await sheets.spreadsheets.values.get({
    spreadsheetId,
    range: `${DRAFT_SHEET}!A2:H`,
  });
  const rows = res.data.values || [];

  // queued の行番号を収集 (1-indexed, offset by header row)
  const updates = [];
  rows.forEach((row, i) => {
    if (row[6] === "queued") {
      updates.push({ rowIndex: i + 2, type: row[1] || "", text: (row[2] || "").slice(0, 40) });
    }
  });

  if (updates.length === 0) {
    console.log("queued の投稿なし。クリア不要。");
    return;
  }

  console.log(`${updates.length}件を rejected に変更します:`);
  updates.forEach((u) => console.log(`  行${u.rowIndex}: ${u.type} — ${u.text}`));

  // バッチ更新
  const data = updates.map((u) => ({
    range: `${DRAFT_SHEET}!G${u.rowIndex}`,
    values: [["rejected"]],
  }));

  await sheets.spreadsheets.values.batchUpdate({
    spreadsheetId,
    requestBody: { valueInputOption: "RAW", data },
  });

  console.log("✅ クリア完了");
}

main().catch((e) => { console.error(e.message); process.exit(1); });
