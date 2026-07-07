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

import {
  loadEnv,
  readJson,
  writeJson,
  checkArticleKillSwitch,
} from "../src/lib/x-agent-utils.mjs";

loadEnv();

const SITE_URL = "https://camp-gear-lab.com";

// googleapis は巨大パッケージで、環境によっては import だけで極端に遅く/ハングする
// （dry-run では Google API を一切使わないのに読み込みで詰まる）。
// そこで「実際に Indexing / Sheets を呼ぶ時だけ遅延ロード」し、
// import・API呼び出しの双方にタイムアウトを掛けて、公開のコア処理を止めない。
function withTimeout(promise, ms, label) {
  let timer;
  const timeout = new Promise((_, reject) => {
    timer = setTimeout(() => reject(new Error(`${label} タイムアウト(${ms}ms)`)), ms);
  });
  return Promise.race([promise, timeout]).finally(() => clearTimeout(timer));
}

let _google = null;
async function loadGoogle() {
  if (_google) return _google;
  const mod = await withTimeout(import("googleapis"), 30_000, "googleapis 読み込み");
  _google = mod.google;
  return _google;
}

function jstDateString(d = new Date()) {
  return new Date(d.getTime() + 9 * 60 * 60 * 1000).toISOString().slice(0, 10);
}

function jstIsoString(d = new Date()) {
  const shifted = new Date(d.getTime() + 9 * 60 * 60 * 1000);
  return `${shifted.toISOString().slice(0, 19)}+09:00`;
}

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
    const google = await loadGoogle();
    const credentials = JSON.parse(credentialsJson);
    const auth = new google.auth.GoogleAuth({
      credentials,
      scopes: ["https://www.googleapis.com/auth/indexing"],
    });
    const indexing = google.indexing({ version: "v3", auth });
    const url = `${SITE_URL}/articles/${slug}`;
    await withTimeout(indexing.urlNotifications.publish({
      requestBody: { url, type: "URL_UPDATED" },
    }), 30_000, "Indexing publish");
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
    const google = await loadGoogle();
    const credentials = JSON.parse(process.env.GOOGLE_CREDENTIALS || "{}");
    const auth = new google.auth.GoogleAuth({
      credentials,
      scopes: ["https://www.googleapis.com/auth/spreadsheets"],
    });
    const sheets = google.sheets({ version: "v4", auth });

    const now = new Date();
    const id = `xp-${jstDateString(now).replace(/-/g, "")}-art-${Math.random().toString(36).slice(2, 6)}`;
    const url = `${SITE_URL}/articles/${article.slug}?utm_source=x&utm_medium=social&utm_campaign=article_promo`;

    const rawExcerpt = article.excerpt || article.content?.slice(0, 120) || "";
    const excerpt = rawExcerpt.length > 100
      ? rawExcerpt.slice(0, 100) + "..."
      : rawExcerpt;

    // リンクは本文に入れない（インプレッション低下防止）
    // URLはE列に設定し、IFTTTリプライで投稿する想定
    const text = excerpt
      ? `${article.title}\n\n${excerpt}`
      : article.title;

    // 翌日をスケジュール日に設定
    const scheduledDate = jstDateString(new Date(now.getTime() + 24 * 60 * 60 * 1000));

    const row = [
      id,                       // A: id
      "article_promo",          // B: type
      text,                     // C: text
      article.slug,             // D: articleSlug
      url,                      // E: url
      "",                       // F: hashtags（ハッシュタグ禁止）
      "draft",                  // G: status (手動承認が必要)
      scheduledDate,            // H: scheduledDate
      jstIsoString(now),        // I: generatedAt
      "",                       // J: postedAt
      "camp",                   // K: axis
      "",                       // L: seedId
      "",                       // M: validationErrors
      "false",                  // N: autoApproved
    ];

    await withTimeout(sheets.spreadsheets.values.append({
      spreadsheetId,
      range: "下書き管理!A:N",
      valueInputOption: "RAW",
      requestBody: { values: [row] },
    }), 30_000, "Sheets append");

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
  // JST (UTC+9) で日付を取得（UTC基準だと日付がずれる）
  const today = jstDateString();
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
    target.publishedAt = jstIsoString();
    // updatedAtを進めないと、sync時のauto-pullがDB側のdraft状態で
    // 公開フラグを巻き戻す（pull-from-supabase.jsのupdatedAt比較が効かない）
    target.updatedAt = new Date().toISOString();
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

      // 外部指標チェック（AI採点に加えて機械的に検証）
      const contentLen = (article.content || "").length;
      const hasInternalLink =
        /\[.+?\]\(\/articles\//.test(article.content || "") ||
        /\{\{(comparison|ranking|product):/.test(article.content || "");
      const hasProductTag = /\{\{(comparison|ranking|product):/.test(article.content || "");
      const faqCount = (article.faqs || []).length;
      const hasMeta = (article.metaDescription || "").length >= 50;

      // ブロッキングチェック（不合格なら公開スキップ）
      const blockers = [];
      if (contentLen < 2000) blockers.push(`文字数不足(${contentLen})`);
      if (faqCount < 2) blockers.push(`FAQ不足(${faqCount}問)`);

      // 警告チェック（公開はブロックしない）
      const warnings = [];
      if (!hasInternalLink) warnings.push("内部リンクなし");
      if (!hasProductTag) warnings.push("商品タグなし(comparison/ranking/product)");
      if (!hasMeta) warnings.push("metaDescription短い");

      if (warnings.length > 0) {
        console.warn(`  ⚠ 品質警告（公開は継続）: ${warnings.join(", ")}`);
      }
      if (blockers.length > 0) {
        console.warn(`  ✗ 品質チェック不合格: ${blockers.join(", ")}`);
        console.warn("  → 公開スキップ（手動確認が必要）");
        continue;
      }
      console.log(`  ✓ 品質チェック合格: ${contentLen}文字, FAQ${faqCount}問`);

      article.status = "published";
      article.publishedAt = jstIsoString();
      // updatedAtを進めないと、sync時のauto-pullがDB側のdraft状態で
      // 公開フラグを巻き戻す（pull-from-supabase.jsのupdatedAt比較が効かない）
      article.updatedAt = new Date().toISOString();
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
