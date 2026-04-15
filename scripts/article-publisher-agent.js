#!/usr/bin/env node

/**
 * Article Publisher Agent — 品質判定→公開 / draft + Indexing API + X連携
 *
 * articles.json の中から公開条件を満たす記事を published に変更し、
 * Google Indexing API でインデックス登録、X投稿パイプラインに article_promo を連携する。
 *
 * 使い方:
 *   node scripts/article-publisher-agent.js                # 本日公開予定の記事を公開
 *   node scripts/article-publisher-agent.js --dry-run      # 表示のみ
 *   node scripts/article-publisher-agent.js --force id     # 強制公開
 */

import { google } from "googleapis";
import {
  loadEnv,
  readJson,
  writeJson,
  checkArticleKillSwitch,
} from "../src/lib/x-agent-utils.mjs";

loadEnv();

const SITE_URL = "https://camp-gear-lab.com";

// ─── CLI ─────────────────────────────────────────────

function parseArgs() {
  const args = process.argv.slice(2);
  const opts = { dryRun: false, forceId: null };
  for (let i = 0; i < args.length; i++) {
    switch (args[i]) {
      case "--dry-run": opts.dryRun = true; break;
      case "--force":   opts.forceId = args[++i]; break;
    }
  }
  return opts;
}

// ─── Google Indexing API ─────────────────────────────

async function notifyGoogleIndex(slug) {
  const credentialsJson = process.env.INDEXING_CREDENTIALS;
  if (!credentialsJson) {
    console.log("[article-publisher] INDEXING_CREDENTIALS 未設定。Indexingスキップ。");
    return;
  }

  try {
    const credentials = JSON.parse(credentialsJson);
    const auth = new google.auth.GoogleAuth({
      credentials,
      scopes: ["https://www.googleapis.com/auth/indexing"],
    });
    const indexing = google.indexing({ version: "v3", auth });
    const url = `${SITE_URL}/articles/${slug}`;
    await indexing.urlNotifications.publish({
      requestBody: { url, type: "URL_UPDATED" },
    });
    console.log(`[article-publisher] Indexing API: ${url}`);
  } catch (err) {
    console.warn(`[article-publisher] Indexing API エラー: ${err.message}`);
  }
}

// ─── X投稿連携（article_promo を下書き管理シートに追加） ───

async function createArticlePromo(article) {
  const spreadsheetId = process.env.X_SHEET_ID;
  if (!spreadsheetId) {
    console.log("[article-publisher] X_SHEET_ID 未設定。X連携スキップ。");
    return;
  }

  try {
    const credentials = JSON.parse(process.env.GOOGLE_CREDENTIALS || "{}");
    const auth = new google.auth.GoogleAuth({
      credentials,
      scopes: ["https://www.googleapis.com/auth/spreadsheets"],
    });
    const sheets = google.sheets({ version: "v4", auth });

    const now = new Date();
    const id = `xp-${now.toISOString().slice(0, 10).replace(/-/g, "")}-art-${Math.random().toString(36).slice(2, 6)}`;
    const url = `${SITE_URL}/articles/${article.slug}?utm_source=x&utm_medium=social&utm_campaign=article_promo`;

    const rawExcerpt = article.excerpt || article.content?.slice(0, 120) || "";
    const excerpt = rawExcerpt.length > 100
      ? rawExcerpt.slice(0, 100) + "..."
      : rawExcerpt;

    const text = excerpt
      ? `${article.title}\n\n${excerpt}\n\n詳しくはこちら\n${url}\n\n#アウトドア #キャンプ`
      : `${article.title}\n\n詳しくはこちら\n${url}\n\n#アウトドア #キャンプ`;

    // 翌日をスケジュール日に設定
    const scheduledDate = new Date(now.getTime() + 24 * 60 * 60 * 1000)
      .toISOString().slice(0, 10);

    const row = [
      id,                       // A: id
      "article_promo",          // B: type
      text,                     // C: text
      article.slug,             // D: articleSlug
      url,                      // E: url
      "#アウトドア #キャンプ",   // F: hashtags
      "draft",                  // G: status (手動承認が必要)
      scheduledDate,            // H: scheduledDate
      now.toISOString(),        // I: generatedAt
      "",                       // J: postedAt
      "camp",                   // K: axis
      "",                       // L: seedId
      "",                       // M: validationErrors
      "false",                  // N: autoApproved
    ];

    await sheets.spreadsheets.values.append({
      spreadsheetId,
      range: "下書き管理!A:N",
      valueInputOption: "RAW",
      requestBody: { values: [row] },
    });

    console.log(`[article-publisher] X article_promo 作成: ${id}`);
  } catch (err) {
    console.warn(`[article-publisher] X連携エラー: ${err.message}`);
  }
}

// ─── メイン ──────────────────────────────────────────

async function main() {
  const opts = parseArgs();

  const ks = checkArticleKillSwitch();
  if (ks.killed) {
    console.error(`[article-publisher] ${ks.reason}`);
    process.exit(1);
  }

  const articles = readJson("articles.json") || [];
  const today = new Date().toISOString().slice(0, 10);
  let updated = false;

  // 強制公開モード
  if (opts.forceId) {
    const target = articles.find((a) => a.id === opts.forceId);
    if (!target) {
      console.error(`[article-publisher] 記事 ${opts.forceId} が見つかりません`);
      process.exit(1);
    }
    console.log(`[article-publisher] 強制公開: ${target.title}`);
    target.status = "published";
    target.publishedAt = new Date().toISOString();
    updated = true;

    if (!opts.dryRun) {
      await notifyGoogleIndex(target.slug);
      await createArticlePromo(target);
    }
  } else {
    // 本日公開予定の記事を処理
    const candidates = articles.filter((a) =>
      a.autoGenerated &&
      a.status !== "published" &&
      a.scheduledPublishDate &&
      a.scheduledPublishDate <= today &&
      (a.qualityScore || 0) >= 6.0
    );

    if (candidates.length === 0) {
      console.log("[article-publisher] 本日公開予定の記事はありません");
      return;
    }

    console.log(`[article-publisher] 公開候補: ${candidates.length}件`);

    for (const article of candidates) {
      console.log(`\n[article-publisher] 公開: ${article.title}`);
      console.log(`  スコア: ${article.qualityScore} / 予定日: ${article.scheduledPublishDate}`);

      article.status = "published";
      article.publishedAt = new Date().toISOString();
      updated = true;

      if (!opts.dryRun) {
        await notifyGoogleIndex(article.slug);
        await createArticlePromo(article);
      } else {
        console.log("  [DRY RUN] 公開処理をスキップ");
      }
    }
  }

  if (updated && !opts.dryRun) {
    writeJson("articles.json", articles);
    console.log("\n[article-publisher] articles.json を更新しました");
  }

  // draft のまま放置されている記事の警告
  const staleDrafts = articles.filter((a) =>
    a.autoGenerated &&
    a.status === "draft" &&
    a.scheduledPublishDate &&
    a.scheduledPublishDate < today
  );
  if (staleDrafts.length > 0) {
    console.warn(`\n[article-publisher] 警告: 公開予定日を過ぎた下書き ${staleDrafts.length}件`);
    for (const a of staleDrafts) {
      console.warn(`  - ${a.title} (スコア: ${a.qualityScore || "N/A"}, 予定: ${a.scheduledPublishDate})`);
    }
  }
}

main().catch((err) => {
  console.error("[article-publisher] エラー:", err.message);
  process.exit(1);
});
