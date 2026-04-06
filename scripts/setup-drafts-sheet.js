#!/usr/bin/env node

/**
 * 「下書き管理」シートをセットアップする
 * x-posts.json の代わりに Google Sheets で下書きを管理するため
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

async function setup() {
  const spreadsheetId = process.env.X_SHEET_ID;
  if (!spreadsheetId) {
    console.error("X_SHEET_ID が設定されていません");
    process.exit(1);
  }

  const credentials = JSON.parse(process.env.GOOGLE_CREDENTIALS);
  const auth = new google.auth.GoogleAuth({
    credentials,
    scopes: ["https://www.googleapis.com/auth/spreadsheets"],
  });
  const sheets = google.sheets({ version: "v4", auth });

  const sheetName = "下書き管理";
  const headers = [
    "id",
    "type",
    "text",
    "articleSlug",
    "url",
    "hashtags",
    "status",
    "scheduledDate",
    "generatedAt",
    "postedAt",
  ];

  // シートが存在するか確認
  try {
    const res = await sheets.spreadsheets.get({ spreadsheetId });
    const existing = res.data.sheets.find(
      (s) => s.properties.title === sheetName
    );

    if (existing) {
      console.log(`シート「${sheetName}」は既に存在します`);
    } else {
      await sheets.spreadsheets.batchUpdate({
        spreadsheetId,
        requestBody: {
          requests: [{ addSheet: { properties: { title: sheetName } } }],
        },
      });
      console.log(`シート「${sheetName}」を作成しました`);
    }

    // ヘッダーを設定
    await sheets.spreadsheets.values.update({
      spreadsheetId,
      range: `${sheetName}!A1:J1`,
      valueInputOption: "RAW",
      requestBody: { values: [headers] },
    });
    console.log("ヘッダーを設定しました:", headers.join(", "));

    // 既存の x-posts.json があれば移行
    const xPostsPath = path.join(__dirname, "..", "data", "x-posts.json");
    if (fs.existsSync(xPostsPath)) {
      const posts = JSON.parse(fs.readFileSync(xPostsPath, "utf-8"));
      if (posts.length > 0) {
        const rows = posts.map((p) => [
          p.id,
          p.type,
          p.text,
          p.articleSlug || "",
          p.url || "",
          p.hashtags || "",
          p.status,
          p.scheduledDate,
          p.generatedAt,
          p.postedAt || "",
        ]);

        await sheets.spreadsheets.values.append({
          spreadsheetId,
          range: `${sheetName}!A:J`,
          valueInputOption: "RAW",
          requestBody: { values: rows },
        });
        console.log(`${posts.length}件の既存データを移行しました`);
      }
    }

    console.log("\nセットアップ完了！");
  } catch (err) {
    console.error("エラー:", err.message);
    process.exit(1);
  }
}

setup();
