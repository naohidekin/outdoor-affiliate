#!/usr/bin/env node

/**
 * Threads 投稿スクリプト
 *
 * 「下書き管理」シートから status=queued かつ threads_status（V列）が空の行を取得し、
 * Meta Threads API v1.0 で投稿する。
 * X投稿と同じコンテンツを利用しつつ、Threads は 500 文字 + リンク埋め込みが可能。
 *
 * 事前準備:
 *   1. developers.facebook.com でアプリ作成 → Threads API 追加
 *   2. threads_basic + threads_content_publish 権限を取得
 *   3. 長期アクセストークン（60日有効）を生成
 *   4. .env.local に追記:
 *      THREADS_USER_ID=数字のユーザーID
 *      THREADS_ACCESS_TOKEN=xxxxx
 *      THREADS_USERNAME=camp_gear_lab  （投稿URLの組み立て用・任意）
 *
 * 使い方:
 *   node scripts/post-to-threads.js            # 1件投稿
 *   node scripts/post-to-threads.js --max=3    # 最大3件
 *   node scripts/post-to-threads.js --dry-run  # 対象確認のみ
 *   node scripts/post-to-threads.js --refresh  # アクセストークン更新
 */

import { google } from "googleapis";
import { loadEnv, checkKillSwitch } from "../src/lib/x-agent-utils.mjs";

loadEnv();

const DRAFT_SHEET = "下書き管理";
const BASE_URL = "https://graph.threads.net/v1.0";

// ─── CLI ─────────────────────────────────────────────

function parseArgs() {
  const args = process.argv.slice(2);
  return {
    dryRun: args.includes("--dry-run"),
    refresh: args.includes("--refresh"),
    immediate: args.includes("--immediate"),
    max: parseInt(args.find((a) => a.startsWith("--max="))?.split("=")[1] || "1"),
  };
}

// ─── Threads API ──────────────────────────────────────

/**
 * コンテナ作成（テキスト投稿）
 */
async function createContainer(userId, text, accessToken) {
  const url = `${BASE_URL}/${userId}/threads`;
  const params = new URLSearchParams({
    media_type: "TEXT",
    text,
    access_token: accessToken,
  });
  const res = await fetch(`${url}?${params}`, { method: "POST" });
  const json = await res.json();
  if (json.error) throw new Error(`Container 作成エラー: ${json.error.message}`);
  if (!json.id) throw new Error(`Container ID が返らない: ${JSON.stringify(json)}`);
  return json.id;
}

/**
 * コンテナのステータスをポーリング（FINISHED になるまで待つ）
 */
async function waitForContainer(containerId, accessToken, maxWaitMs = 60_000) {
  const started = Date.now();
  while (Date.now() - started < maxWaitMs) {
    const url = `${BASE_URL}/${containerId}`;
    const params = new URLSearchParams({
      fields: "status,error_message",
      access_token: accessToken,
    });
    const res = await fetch(`${url}?${params}`);
    const json = await res.json();

    if (json.status === "FINISHED") return;
    if (json.status === "ERROR") throw new Error(`Container ERROR: ${json.error_message}`);
    if (json.status === "EXPIRED") throw new Error("Container EXPIRED");

    // IN_PROGRESS → 5秒待って再確認
    await new Promise((r) => setTimeout(r, 5_000));
  }
  throw new Error("Container タイムアウト（60秒）");
}

/**
 * コンテナを公開
 */
async function publishContainer(userId, containerId, accessToken) {
  const url = `${BASE_URL}/${userId}/threads_publish`;
  const params = new URLSearchParams({
    creation_id: containerId,
    access_token: accessToken,
  });
  const res = await fetch(`${url}?${params}`, { method: "POST" });
  const json = await res.json();
  if (json.error) throw new Error(`Publish エラー: ${json.error.message}`);
  if (!json.id) throw new Error(`Post ID が返らない: ${JSON.stringify(json)}`);
  return json.id;
}

/**
 * アクセストークンを長期トークンとして更新（60日延長）
 */
async function refreshAccessToken(accessToken) {
  const params = new URLSearchParams({
    grant_type: "th_refresh_token",
    access_token: accessToken,
  });
  const res = await fetch(`${BASE_URL}/refresh_access_token?${params}`);
  const json = await res.json();
  if (json.error) throw new Error(`Token 更新エラー: ${json.error.message}`);
  return json.access_token;
}

// ─── Sheets ──────────────────────────────────────────

async function getSheets() {
  const credentials = JSON.parse(process.env.GOOGLE_CREDENTIALS);
  const auth = new google.auth.GoogleAuth({
    credentials,
    scopes: ["https://www.googleapis.com/auth/spreadsheets"],
  });
  return google.sheets({ version: "v4", auth });
}

// ─── テキスト組み立て ─────────────────────────────────

/**
 * X用テキスト（最大280文字）を Threads 用に拡張。
 * - sourceUrl を末尾に追加（500文字以内に収まる場合）
 * - 既にリンクが含まれている場合は追加しない
 */
function buildThreadsText(text, sourceUrl) {
  let threadsText = (text || "").trim();
  if (!threadsText) return null;

  if (sourceUrl && !threadsText.includes(sourceUrl)) {
    const withUrl = `${threadsText}\n\n${sourceUrl}`;
    if (withUrl.length <= 500) threadsText = withUrl;
  }

  if (threadsText.length > 500) {
    threadsText = threadsText.slice(0, 497) + "...";
  }
  return threadsText;
}

// ─── メイン ──────────────────────────────────────────

async function main() {
  const opts = parseArgs();
  if (!opts.dryRun && !opts.immediate) {
    const waitMs = Math.floor(Math.random() * 60 * 60 * 1000);
    console.log(`[random delay] ${Math.round(waitMs / 60000)}m before posting...`);
    await new Promise(r => setTimeout(r, waitMs));
  }

  // KILL SWITCH
  const ks = checkKillSwitch();
  if (ks.killed) {
    console.log(`[threads-poster] KILL SWITCH 有効: ${ks.reason}`);
    process.exit(0);
  }

  const userId = process.env.THREADS_USER_ID;
  const accessToken = process.env.THREADS_ACCESS_TOKEN;
  const username = process.env.THREADS_USERNAME || "camp_gear_lab";

  if (!userId || !accessToken) {
    console.error("[threads-poster] THREADS_USER_ID / THREADS_ACCESS_TOKEN が未設定");
    console.error("  → .env.local に追記してください");
    process.exit(1);
  }

  if (!process.env.X_SHEET_ID) {
    console.error("[threads-poster] X_SHEET_ID が未設定");
    process.exit(1);
  }

  // トークン更新モード
  if (opts.refresh) {
    console.log("[threads-poster] アクセストークン更新中...");
    const newToken = await refreshAccessToken(accessToken);
    console.log("[threads-poster] 新しいトークン:");
    console.log(newToken);
    console.log("\n.env.local の THREADS_ACCESS_TOKEN を上記に更新してください");
    return;
  }

  const sheets = await getSheets();
  const spreadsheetId = process.env.X_SHEET_ID;

  // 下書き管理シートを読み込み（W列まで）
  const res = await sheets.spreadsheets.values.get({
    spreadsheetId,
    range: `${DRAFT_SHEET}!A2:W`,
  });
  const rows = res.data.values || [];

  // 候補: status=queued または posted、かつ threads_status（V列 = index 21）が空
  const candidates = rows
    .map((row, i) => ({ row, rowIndex: i + 2 }))
    .filter(({ row }) => {
      const status = row[6]; // G: status
      const threadsStatus = row[21]; // V: threads_status
      return (status === "queued" || status === "posted") && !threadsStatus;
    })
    .slice(0, opts.max);

  if (candidates.length === 0) {
    console.log("[threads-poster] 投稿対象なし（queued/posted かつ threads未投稿の行がない）");
    return;
  }

  console.log(`[threads-poster] 投稿対象: ${candidates.length}件\n`);

  for (const { row, rowIndex } of candidates) {
    const text = row[2] || "";  // C: text
    const sourceUrl = row[4] || "";  // E: url

    const threadsText = buildThreadsText(text, sourceUrl);
    if (!threadsText) {
      console.warn(`  行${rowIndex}: テキストが空 → スキップ`);
      continue;
    }

    console.log(`[threads-poster] 行${rowIndex}: ${threadsText.slice(0, 80)}...`);
    console.log(`  文字数: ${threadsText.length}`);

    if (opts.dryRun) {
      console.log("  [DRY RUN] スキップ\n");
      continue;
    }

    try {
      // Step 1: コンテナ作成
      const containerId = await createContainer(userId, threadsText, accessToken);
      console.log(`  コンテナ作成: ${containerId}`);

      // Step 2: FINISHED になるまで待機（最大60秒）
      await waitForContainer(containerId, accessToken);

      // Step 3: 公開
      const postId = await publishContainer(userId, containerId, accessToken);
      const postUrl = `https://www.threads.net/@${username}/post/${postId}`;
      console.log(`  投稿完了: ${postUrl}`);

      // Sheets 更新（V: threads_status, W: threads_post_url）
      await sheets.spreadsheets.values.update({
        spreadsheetId,
        range: `${DRAFT_SHEET}!V${rowIndex}:W${rowIndex}`,
        valueInputOption: "RAW",
        requestBody: { values: [["posted", postUrl]] },
      });

      // 連続投稿時は30秒間隔
      if (candidates.length > 1) await new Promise((r) => setTimeout(r, 30_000));
    } catch (err) {
      console.error(`  エラー: ${err.message}`);
      try {
        await sheets.spreadsheets.values.update({
          spreadsheetId,
          range: `${DRAFT_SHEET}!V${rowIndex}`,
          valueInputOption: "RAW",
          requestBody: { values: [["error"]] },
        });
      } catch { /* Sheets更新失敗は無視 */ }
    }
  }

  console.log("\n[threads-poster] 完了");
}

main().catch((err) => {
  console.error("[threads-poster] 致命的エラー:", err.message);
  process.exit(1);
});
