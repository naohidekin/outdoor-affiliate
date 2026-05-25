#!/usr/bin/env node

/**
 * エンゲージエージェント
 * viral-scout-results.json から camp/doctor/parenting 軸の高エンゲージ投稿を取得し、
 * 既に生成済みの suggestion テキストを Google Sheets「エンゲージ管理」タブに
 * pending として書き込む（手動承認後に post-to-x.js でポスト）。
 *
 * 使い方:
 *   node scripts/engager-agent.js           # 最大5件書き込み
 *   node scripts/engager-agent.js --max=3   # 最大3件
 *   node scripts/engager-agent.js --dry-run # Sheets書き込みなし（テキスト確認のみ）
 */

import { google } from "googleapis";
import fs from "fs";
import path from "path";
import { fileURLToPath } from "url";
import { loadEnv } from "../src/lib/x-agent-utils.mjs";

loadEnv();

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const DATA_DIR = path.join(__dirname, "..", "data");

const ENGAGE_SHEET = "エンゲージ管理";

// ai 軸は廃止（2026-05-02）。camp/doctor/parenting のみ対象
const ALLOWED_AXES = new Set(["camp", "parenting", "doctor"]);

// ─── CLI オプション ───────────────────────────────────────

function parseArgs() {
  const args = process.argv.slice(2);
  const opts = { max: 5, dryRun: false };
  for (let i = 0; i < args.length; i++) {
    const arg = args[i];
    const eqIdx = arg.indexOf("=");
    const key = eqIdx !== -1 ? arg.slice(0, eqIdx) : arg;
    const val = eqIdx !== -1 ? arg.slice(eqIdx + 1) : args[i + 1];
    switch (key) {
      case "--max": opts.max = parseInt(val, 10) || 5; if (eqIdx === -1) i++; break;
      case "--dry-run": opts.dryRun = true; break;
    }
  }
  return opts;
}

// ─── Google Sheets ───────────────────────────────────────

async function getSheets() {
  const credentials = JSON.parse(process.env.GOOGLE_CREDENTIALS);
  const auth = new google.auth.GoogleAuth({
    credentials,
    scopes: ["https://www.googleapis.com/auth/spreadsheets"],
  });
  return google.sheets({ version: "v4", auth });
}

/**
 * エンゲージ管理シートに既に登録済みの targetTweetId を取得（重複防止）。
 */
async function getExistingTargetIds(sheets, spreadsheetId) {
  try {
    const res = await sheets.spreadsheets.values.get({
      spreadsheetId,
      range: `${ENGAGE_SHEET}!J2:J`,
    });
    const rows = res.data.values || [];
    return new Set(rows.flat().filter(Boolean));
  } catch {
    return new Set();
  }
}

/**
 * エンゲージ管理シートに pending 行を追記する。
 * スキーマ: status | postType | text | imageUrl | sourceUrl | scheduledAt | postedAt | postUrl | _ | targetTweetId
 */
async function appendToEngageSheet(sheets, spreadsheetId, rows) {
  await sheets.spreadsheets.values.append({
    spreadsheetId,
    range: `${ENGAGE_SHEET}!A1`,
    valueInputOption: "RAW",
    insertDataOption: "INSERT_ROWS",
    requestBody: { values: rows },
  });
}

// ─── メイン ──────────────────────────────────────────────

async function run(opts) {
  const spreadsheetId = process.env.X_SHEET_ID;
  if (!spreadsheetId) {
    console.error("X_SHEET_ID が設定されていません");
    process.exit(1);
  }

  // engage-results.json を優先し、なければ viral-scout-results.json にフォールバック
  const engagePath = path.join(DATA_DIR, "engage-results.json");
  const scoutPath = path.join(DATA_DIR, "viral-scout-results.json");

  let allPosts = [];

  if (fs.existsSync(engagePath)) {
    const engageData = JSON.parse(fs.readFileSync(engagePath, "utf-8"));
    const engagePosts = engageData.viralPosts || engageData.posts || [];
    allPosts = allPosts.concat(engagePosts);
    console.log(`engage-results.json から ${engagePosts.length} 件読み込み`);
  }

  if (fs.existsSync(scoutPath)) {
    const scoutData = JSON.parse(fs.readFileSync(scoutPath, "utf-8"));
    const scoutPosts = scoutData.viralPosts || scoutData.posts || [];
    // engage-results と重複しない tweetId のみ追加
    const existingIds = new Set(allPosts.map((p) => p.tweetId));
    const newPosts = scoutPosts.filter((p) => !existingIds.has(p.tweetId));
    allPosts = allPosts.concat(newPosts);
    if (newPosts.length > 0) {
      console.log(`viral-scout-results.json から ${newPosts.length} 件追加読み込み`);
    }
  }

  if (allPosts.length === 0) {
    console.error("engage-results.json も viral-scout-results.json も見つかりません");
    process.exit(1);
  }

  const posts = allPosts;

  // camp/doctor/parenting 軸のみ、draft な generatedContent が存在する投稿を収集
  // generatedContent は { quoteTweet: {text, status}, reply: {text, status} } の形式
  const candidates = [];
  for (const post of posts) {
    if (!ALLOWED_AXES.has(post.axis)) continue;
    const gc = post.generatedContent;
    if (!gc) continue;

    // quoteTweet が draft なら優先、なければ reply を使用
    if (gc.quoteTweet?.status === "draft") {
      candidates.push({ post, suggestion: gc.quoteTweet, postType: "quote" });
    } else if (gc.reply?.status === "draft") {
      candidates.push({ post, suggestion: gc.reply, postType: "reply" });
    }
  }

  if (candidates.length === 0) {
    console.log("エンゲージ候補がありません（draft な generatedContent が存在しない）");
    return;
  }

  // Sheets接続
  let sheets;
  try {
    sheets = await getSheets();
  } catch (err) {
    console.error(`Sheets接続失敗: ${err.message}`);
    process.exit(1);
  }

  // 既存の targetTweetId を取得（重複防止）
  const existingIds = await getExistingTargetIds(sheets, spreadsheetId);
  const filtered = candidates.filter((c) => !existingIds.has(c.post.tweetId));

  if (filtered.length === 0) {
    console.log("エンゲージ候補がありません（全て既にシートに登録済み）");
    return;
  }

  const targets = filtered.slice(0, opts.max);
  console.log(`エンゲージ候補: ${filtered.length}件 → ${targets.length}件を処理 (max=${opts.max})`);

  const sheetRows = [];

  for (const { post, suggestion, postType } of targets) {
    const text = suggestion.text || "";
    const sourceUrl = `https://x.com/${post.authorUsername}/status/${post.tweetId}`;

    console.log(`\n[${post.axis}] @${post.authorUsername} (♥${post.metrics?.likes || "?"} フォロワー${post.authorFollowers || "?"})`);
    console.log(`  引用元: ${(post.text || "").slice(0, 60)}...`);
    console.log(`  生成文: ${text.slice(0, 80)}...`);

    if (!opts.dryRun) {
      sheetRows.push([
        "pending",    // status — 管理者が確認後 "ready" に変更してポスト
        postType,     // postType — "quote" or "reply"
        text,         // 生成テキスト
        "",           // imageUrl
        sourceUrl,    // 引用元URL（管理UIで確認用）
        "",           // scheduledAt
        "",           // postedAt
        "",           // postUrl
        "",           // _（予備）
        post.tweetId, // targetTweetId — post-to-x.js が引用RT/リプライに使用
      ]);
    }
  }

  if (opts.dryRun) {
    console.log("\n[DRY RUN] Sheets 書き込みをスキップ");
    return;
  }

  if (sheetRows.length === 0) {
    console.log("書き込み対象がありません");
    return;
  }

  await appendToEngageSheet(sheets, spreadsheetId, sheetRows);
  console.log(`\nエンゲージ管理シートに ${sheetRows.length} 件追加 (status=pending)`);

  // 各ソースファイルの status を "queued" に更新（重複投入防止）
  let engageUpdated = 0;
  let scoutUpdated = 0;

  if (fs.existsSync(engagePath)) {
    const engageData = JSON.parse(fs.readFileSync(engagePath, "utf-8"));
    const engagePosts = engageData.viralPosts || engageData.posts || [];
    for (const { post, suggestion, postType } of targets) {
      const tp = engagePosts.find((p) => p.tweetId === post.tweetId);
      if (!tp?.generatedContent) continue;
      const gcKey = postType === "quote" ? "quoteTweet" : "reply";
      const entry = tp.generatedContent[gcKey];
      if (entry && entry.text === suggestion.text) {
        entry.status = "queued";
        engageUpdated++;
      }
    }
    if (engageUpdated > 0) {
      fs.writeFileSync(engagePath, JSON.stringify(engageData, null, 2) + "\n", "utf-8");
      console.log(`engage-results.json の ${engageUpdated}件を queued に更新`);
    }
  }

  if (fs.existsSync(scoutPath)) {
    const scoutData = JSON.parse(fs.readFileSync(scoutPath, "utf-8"));
    const scoutPosts = scoutData.viralPosts || scoutData.posts || [];
    for (const { post, suggestion, postType } of targets) {
      const tp = scoutPosts.find((p) => p.tweetId === post.tweetId);
      if (!tp?.generatedContent) continue;
      const gcKey = postType === "quote" ? "quoteTweet" : "reply";
      const entry = tp.generatedContent[gcKey];
      if (entry && entry.text === suggestion.text) {
        entry.status = "queued";
        scoutUpdated++;
      }
    }
    if (scoutUpdated > 0) {
      fs.writeFileSync(scoutPath, JSON.stringify(scoutData, null, 2) + "\n", "utf-8");
      console.log(`viral-scout-results.json の ${scoutUpdated}件を queued に更新`);
    }
  }
}

const opts = parseArgs();
run(opts).catch((err) => {
  console.error("エラー:", err.message);
  process.exit(1);
});
