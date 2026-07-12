#!/usr/bin/env node

/**
 * IndexNow 一括送信（初回シード用・手動リカバリ用）
 *
 * 公開済み全記事＋主要ページのURLを IndexNow（Bing/Copilot系）へ一括通知する。
 * 通常運用では article-daily が公開時に1件ずつ自動通知するので、
 * このスクリプトは「初回」「大量リライト後」だけ実行すれば十分。
 *
 * 使い方:
 *   node scripts/indexnow-submit.mjs             # 全公開記事+固定ページを送信
 *   node scripts/indexnow-submit.mjs --dry-run   # 送信せずURL一覧を表示
 *
 * 前提: public/<key>.txt がデプロイ済みであること（キーファイルの実在確認をしてから送る）
 */

import fs from "fs";
import path from "path";
import { fileURLToPath } from "url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const ROOT = path.join(__dirname, "..");
const SITE_URL = "https://camp-gear-lab.com";
const HOST = "camp-gear-lab.com";
const KEY = "945e8303b9c842052e5dfde5850252a3";
const DRY_RUN = process.argv.includes("--dry-run");

const articles = JSON.parse(fs.readFileSync(path.join(ROOT, "data", "articles.json"), "utf-8"));
const categories = JSON.parse(fs.readFileSync(path.join(ROOT, "data", "categories.json"), "utf-8"));

const urls = [
  `${SITE_URL}/`,
  `${SITE_URL}/about`,
  ...categories.map((c) => `${SITE_URL}/category/${c.slug}`),
  ...articles.filter((a) => a.status === "published").map((a) => `${SITE_URL}/articles/${a.slug}`),
];

console.log(`[indexnow] 送信対象 ${urls.length} 件${DRY_RUN ? " [DRY RUN]" : ""}`);

if (DRY_RUN) {
  urls.forEach((u) => console.log("  " + u));
  process.exit(0);
}

// 1. キーファイルの実在確認（未デプロイのまま送ると全件無効になるため）
const keyUrl = `${SITE_URL}/${KEY}.txt`;
const keyRes = await fetch(keyUrl);
const keyBody = (await keyRes.text()).trim();
if (!keyRes.ok || keyBody !== KEY) {
  console.error(`[indexnow] ❌ キーファイルが本番に見つかりません: ${keyUrl}`);
  console.error("先にmainへのマージ→Vercelデプロイを済ませてから再実行してください。");
  process.exit(1);
}
console.log("[indexnow] キーファイル確認OK");

// 2. 一括送信（1リクエスト最大10,000件なので1回で足りる）
const res = await fetch("https://api.indexnow.org/indexnow", {
  method: "POST",
  headers: { "Content-Type": "application/json; charset=utf-8" },
  body: JSON.stringify({ host: HOST, key: KEY, keyLocation: keyUrl, urlList: urls }),
});
console.log(`[indexnow] 送信結果: HTTP ${res.status} ${res.status === 200 || res.status === 202 ? "✅ 受理されました" : "⚠️ " + (await res.text()).slice(0, 200)}`);
