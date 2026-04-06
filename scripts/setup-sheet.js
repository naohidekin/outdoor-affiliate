#!/usr/bin/env node

/**
 * X投稿管理用Google Sheetsを作成するセットアップスクリプト（1回だけ実行）
 */

import { google } from "googleapis";
import fs from "fs";
import path from "path";
import { fileURLToPath } from "url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const ENV_PATH = path.join(__dirname, "..", ".env.local");

async function setup() {
  const credentials = JSON.parse(process.env.GOOGLE_CREDENTIALS);
  const auth = new google.auth.GoogleAuth({
    credentials,
    scopes: [
      "https://www.googleapis.com/auth/spreadsheets",
      "https://www.googleapis.com/auth/drive",
    ],
  });

  const sheets = google.sheets({ version: "v4", auth });
  const drive = google.drive({ version: "v3", auth });

  // 1. スプレッドシート作成
  console.log("スプレッドシートを作成中...");
  const res = await sheets.spreadsheets.create({
    requestBody: {
      properties: { title: "X投稿管理 - camp-gear-lab" },
      sheets: [
        {
          properties: { title: "X投稿管理", index: 0 },
        },
        {
          properties: { title: "投稿ログ", index: 1 },
        },
      ],
    },
  });

  const spreadsheetId = res.data.spreadsheetId;
  const url = res.data.spreadsheetUrl;
  console.log(`作成完了: ${url}`);

  // 2. ヘッダー行を設定
  console.log("ヘッダーを設定中...");
  await sheets.spreadsheets.values.batchUpdate({
    spreadsheetId,
    requestBody: {
      valueInputOption: "RAW",
      data: [
        {
          range: "X投稿管理!A1:H1",
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
        {
          range: "投稿ログ!A1:D1",
          values: [["posted_at", "text", "post_url", "source"]],
        },
      ],
    },
  });

  // 3. ユーザーに共有
  const userEmail = process.argv[2];
  if (userEmail) {
    console.log(`${userEmail} に編集権限を付与中...`);
    await drive.permissions.create({
      fileId: spreadsheetId,
      requestBody: {
        type: "user",
        role: "writer",
        emailAddress: userEmail,
      },
      sendNotificationEmail: false,
    });
  }

  // 4. .env.local の X_SHEET_ID を更新
  let envContent = fs.readFileSync(ENV_PATH, "utf-8");
  envContent = envContent.replace(
    /X_SHEET_ID=.*/,
    `X_SHEET_ID=${spreadsheetId}`
  );
  fs.writeFileSync(ENV_PATH, envContent, "utf-8");

  console.log(`\n--- セットアップ完了 ---`);
  console.log(`スプレッドシートID: ${spreadsheetId}`);
  console.log(`URL: ${url}`);
  console.log(`.env.local の X_SHEET_ID を更新しました`);
}

setup().catch((err) => {
  console.error("エラー:", err.message);
  process.exit(1);
});
