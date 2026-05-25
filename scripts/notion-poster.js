#!/usr/bin/env node
/**
 * Notion 承認 → X 投稿スクリプト
 *
 * 各 Notion DB の ステータス=approved ページを取得し、
 * 対応する X アカウントへ投稿する。
 * 投稿後に Notion のステータスを "posted" に更新し、投稿日時を記録する。
 *
 * 対象 DB:
 *   GearMan Replies     → ギア男 (@camp_gear_lab)    リプライ投稿
 *   ギア男 X Posts       → ギア男 (@camp_gear_lab)    通常投稿
 *   アンブロ X Posts     → アンブロ (san-pedinvestor) 通常投稿
 *   アンブロ Replies     → アンブロ (san-pedinvestor) リプライ投稿
 *   ラボ X Posts         → ラボ                       通常投稿
 *   こどもケアラボ Replies → こどもケアラボ           リプライ投稿
 *   ドクターオート X Posts → ドクターオート           通常投稿
 *
 * 必要な環境変数:
 *   NOTION_TOKEN              — Notion Integration Token
 *   X_API_KEY / X_API_SECRET / X_ACCESS_TOKEN / X_ACCESS_SECRET
 *                             — ギア男 (camp_gear_lab) 用
 *   AMBLE_X_API_KEY / ...     — アンブロ用
 *   LABO_X_API_KEY / ...      — ラボ用
 *   KODOMO_X_API_KEY / ...    — こどもケアラボ用
 *   DROTO_X_API_KEY / ...     — ドクターオート用
 *
 * 使い方:
 *   node scripts/notion-poster.js
 *   node scripts/notion-poster.js --dry-run
 *   node scripts/notion-poster.js --db=gearman-replies
 */

import { TwitterApi } from "twitter-api-v2";
import {
  loadEnv,
  checkKillSwitch,
} from "../src/lib/x-agent-utils.mjs";
import {
  queryApproved,
  markPosted,
  extractText,
  extractUrl,
  extractTweetId,
} from "../src/lib/notion-queue.mjs";

loadEnv();

// ─── CLI ─────────────────────────────────────────────

function parseArgs() {
  const args = process.argv.slice(2);
  const opts = { dryRun: false, dbFilter: null };
  for (const arg of args) {
    if (arg === "--dry-run") opts.dryRun = true;
    else if (arg.startsWith("--db=")) opts.dbFilter = arg.slice(5);
  }
  return opts;
}

// ─── DB 設定 ──────────────────────────────────────────

/**
 * type "reply": リプライ投稿。textField のテキストを urlField の tweetId 宛に返信する。
 * type "post":  通常投稿。textField のテキストをそのまま投稿する。
 */
const DB_CONFIGS = [
  {
    id: "gearman-replies",
    name: "ギア男 リプライ",
    databaseId: "9feff0c2-142a-49f9-9985-d4d72868ad26",
    type: "reply",
    textField: "リプライ",
    urlField: "元ポストURL",
    xCreds: "gearman",
  },
  {
    id: "gearman-posts",
    name: "ギア男 X Posts",
    databaseId: "1d9bbe0c-30a5-4bfd-86b3-ced628cf05eb",
    type: "post",
    textField: "本文",
    xCreds: "gearman",
  },
  {
    id: "amble-posts",
    name: "アンブロ X Posts",
    databaseId: "60f51624-34c4-4ada-9511-65a88cf6e6d4",
    type: "post",
    textField: "本文",
    xCreds: "amble",
  },
  {
    id: "amble-replies",
    name: "アンブロ Replies",
    databaseId: "bb14682e-285b-41a5-a0d1-eccecf56e077",
    type: "reply",
    textField: "リプライ",
    urlField: "元ポストURL",
    xCreds: "amble",
  },
  {
    id: "labo-posts",
    name: "ラボ X Posts",
    databaseId: "90e61bd3-ed3c-444c-9032-4c69394759fd",
    type: "post",
    textField: "本文",
    xCreds: "labo",
  },
  {
    id: "kodomo-replies",
    name: "こどもケアラボ Replies",
    databaseId: "8be1d3d2-5fee-4222-ab2e-1c1eba96dc90",
    type: "reply",
    textField: "リプライ",
    urlField: "元ポストURL",
    xCreds: "kodomo",
  },
  {
    id: "droto-posts",
    name: "ドクターオート X Posts",
    databaseId: "3dc0d996-f127-4a15-b280-307deb87dd05",
    type: "post",
    textField: "本文",
    xCreds: "droto",
  },
];

// ─── X クライアント ───────────────────────────────────

/**
 * アカウントキーに対応する環境変数プレフィックスマップ。
 * ギア男だけは既存の変数名 (プレフィックスなし) を使う。
 */
const CREDS_PREFIX = {
  gearman: "",
  amble: "AMBLE_",
  labo: "LABO_",
  kodomo: "KODOMO_",
  droto: "DROTO_",
};

function getXClient(credsKey) {
  const prefix = CREDS_PREFIX[credsKey] ?? credsKey.toUpperCase() + "_";
  const apiKey = process.env[`${prefix}X_API_KEY`];
  const apiSecret = process.env[`${prefix}X_API_SECRET`];
  const accessToken = process.env[`${prefix}X_ACCESS_TOKEN`];
  const accessSecret = process.env[`${prefix}X_ACCESS_SECRET`];

  if (!apiKey || !apiSecret || !accessToken || !accessSecret) {
    return null;
  }
  return new TwitterApi({
    appKey: apiKey,
    appSecret: apiSecret,
    accessToken,
    accessSecret,
  });
}

// ─── 投稿処理 ─────────────────────────────────────────

async function processDb(dbConfig, { dryRun }, token) {
  const { id, name, databaseId, type, textField, urlField, xCreds } = dbConfig;

  let pages;
  try {
    pages = await queryApproved(databaseId, {}, token);
  } catch (err) {
    console.error(`[${name}] Notion 取得失敗: ${err.message}`);
    return { posted: 0, skipped: 0, errors: 1 };
  }

  if (pages.length === 0) {
    console.log(`[${name}] 承認済みなし`);
    return { posted: 0, skipped: 0, errors: 0 };
  }

  console.log(`[${name}] 承認済み ${pages.length} 件`);

  const xClient = getXClient(xCreds);
  if (!xClient) {
    console.warn(
      `[${name}] X 認証情報未設定 (${CREDS_PREFIX[xCreds] || ""}X_API_KEY 等)。スキップ。`
    );
    return { posted: 0, skipped: pages.length, errors: 0 };
  }

  let posted = 0;
  let skipped = 0;
  let errors = 0;

  for (const page of pages) {
    const props = page.properties || {};

    // テキスト取得
    const text = extractText(props[textField]);
    if (!text.trim()) {
      console.warn(`[${name}] page ${page.id}: テキスト空。スキップ。`);
      skipped++;
      continue;
    }

    // リプライ: 元ポスト URL から tweet ID を取得
    let replyToTweetId = null;
    if (type === "reply") {
      const sourceUrl = extractUrl(props[urlField]);
      replyToTweetId = extractTweetId(sourceUrl);
      if (!replyToTweetId) {
        console.warn(
          `[${name}] page ${page.id}: 元ポストURL が取得できないのでスキップ (url=${sourceUrl})`
        );
        skipped++;
        continue;
      }
    }

    // プレビュー表示
    const preview = text.slice(0, 60).replace(/\n/g, " ");
    if (type === "reply") {
      console.log(`  → リプライ to ${replyToTweetId}: ${preview}...`);
    } else {
      console.log(`  → 通常投稿: ${preview}...`);
    }

    if (dryRun) {
      console.log("    [DRY RUN] 投稿スキップ");
      skipped++;
      continue;
    }

    // X 投稿
    let tweetId;
    let postUrl;
    try {
      let result;
      if (type === "reply") {
        result = await xClient.v2.tweet(text, {
          reply: { in_reply_to_tweet_id: replyToTweetId },
        });
      } else {
        result = await xClient.v2.tweet(text);
      }
      tweetId = result.data?.id;
      if (tweetId) {
        postUrl = `https://x.com/i/web/status/${tweetId}`;
      }
      console.log(`    ✓ 投稿完了 (tweet_id: ${tweetId})`);
    } catch (err) {
      console.error(`    ✗ X 投稿失敗: ${err.message}`);
      errors++;
      continue;
    }

    // Notion 更新
    try {
      await markPosted(page.id, { postUrl }, token);
    } catch (err) {
      console.error(`    ✗ Notion 更新失敗 (page: ${page.id}): ${err.message}`);
      // Notion 更新失敗でも投稿自体は成功扱い
    }

    posted++;

    // レート制限対策: DB 内で連続投稿しない (2秒待機)
    if (pages.indexOf(page) < pages.length - 1) {
      await new Promise((r) => setTimeout(r, 2000));
    }
  }

  return { posted, skipped, errors };
}

// ─── メイン ───────────────────────────────────────────

async function main() {
  const opts = parseArgs();

  // Kill switch チェック
  const ks = checkKillSwitch();
  if (ks.killed) {
    console.log(`[notion-poster] Kill Switch 有効 — 停止 (理由: ${ks.reason})`);
    process.exit(0);
  }

  const token = process.env.NOTION_TOKEN;
  if (!token) {
    console.error("[notion-poster] NOTION_TOKEN が設定されていません");
    process.exit(1);
  }

  console.log(`[notion-poster] 開始 ${new Date().toLocaleString("ja-JP")}${opts.dryRun ? " [DRY RUN]" : ""}`);

  const targets = opts.dbFilter
    ? DB_CONFIGS.filter((c) => c.id === opts.dbFilter)
    : DB_CONFIGS;

  if (targets.length === 0) {
    console.error(`[notion-poster] DB が見つかりません: ${opts.dbFilter}`);
    process.exit(1);
  }

  let totalPosted = 0;
  let totalSkipped = 0;
  let totalErrors = 0;

  for (const dbConfig of targets) {
    const result = await processDb(dbConfig, opts, token);
    totalPosted += result.posted;
    totalSkipped += result.skipped;
    totalErrors += result.errors;
  }

  console.log(`\n=== 完了 ===`);
  console.log(`投稿: ${totalPosted} / スキップ: ${totalSkipped} / エラー: ${totalErrors}`);
}

main().catch((err) => {
  console.error("[notion-poster] 致命的エラー:", err.message);
  process.exit(1);
});
