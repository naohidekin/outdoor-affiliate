#!/usr/bin/env node

/**
 * Sitemap を Google Search Console に再送信
 *
 * 既存登録済みのサイトマップを再度 submit してクロール促進。
 * 新記事公開後 / GSCで「検出-未登録」が増えた時に実行。
 *
 * 使い方:
 *   node scripts/resubmit-sitemap.js
 *
 * 前提:
 *   - INDEXING_CREDENTIALS（service account JSON）設定済み
 *   - GSCで service account を「所有者」として追加済み
 */

import { google } from "googleapis";
import { loadEnv } from "../src/lib/x-agent-utils.mjs";

loadEnv();

const SITE_URL = "https://camp-gear-lab.com/";
const SITEMAP_URL = "https://camp-gear-lab.com/sitemap.xml";

function getAuth() {
  const credentials = JSON.parse(process.env.INDEXING_CREDENTIALS || "{}");
  if (!credentials.client_email) {
    throw new Error("INDEXING_CREDENTIALS 未設定または無効");
  }
  return new google.auth.GoogleAuth({
    credentials,
    scopes: ["https://www.googleapis.com/auth/webmasters"],
  });
}

async function main() {
  const auth = getAuth();
  const sc = google.searchconsole({ version: "v1", auth });

  console.log(`[sitemap] 対象: ${SITEMAP_URL}`);

  // 現状確認
  try {
    const list = await sc.sitemaps.list({ siteUrl: SITE_URL });
    const found = list.data.sitemap?.find((s) => s.path === SITEMAP_URL);
    if (found) {
      console.log(`[sitemap] 現在の状態: lastSubmitted=${found.lastSubmitted}`);
      if (found.contents) {
        console.log(`[sitemap] contents: ${JSON.stringify(found.contents)}`);
      }
    } else {
      console.log(`[sitemap] 現在の状態: 未登録（新規送信）`);
    }
  } catch (err) {
    console.warn(`[sitemap] list failed:`, err.message);
  }

  // 再送信
  console.log(`[sitemap] 送信中...`);
  try {
    await sc.sitemaps.submit({
      siteUrl: SITE_URL,
      feedpath: SITEMAP_URL,
    });
    console.log(`[sitemap] ✓ 送信完了`);
  } catch (err) {
    console.error(`[sitemap] submit failed:`, err.message);
    if (err.message?.includes("403") || err.message?.includes("permission")) {
      console.error(
        "[sitemap] 403 — service account を Search Console の「所有者」に追加してください"
      );
      console.error(
        "[sitemap] https://search.google.com/search-console/users から追加可能"
      );
    }
    process.exit(1);
  }

  // 再送信後の状態
  try {
    const list = await sc.sitemaps.list({ siteUrl: SITE_URL });
    const found = list.data.sitemap?.find((s) => s.path === SITEMAP_URL);
    if (found) {
      console.log(
        `[sitemap] 再送信後: lastSubmitted=${found.lastSubmitted}` +
          (found.contents ? ` contents=${JSON.stringify(found.contents)}` : "")
      );
    }
  } catch {}
}

main().catch((err) => {
  console.error("[sitemap] エラー:", err.message);
  process.exit(1);
});
