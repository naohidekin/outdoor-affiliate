#!/usr/bin/env node

/**
 * アルペン(ValueCommerce)導線のパイロット。
 * アルペンが確実に扱うカテゴリの published 記事に、自然な文脈で
 * アルペンアウトドアズのカテゴリページへのリンクを追加する。
 * LinkSwitch導入済みのため、クリック時に自動でアフィリンク化される。
 * ※前提: アルペンがLinkSwitch対応であること（VCのプログラム詳細で要確認）
 * 使い方: node scripts/add-alpen-links-pilot.mjs  →  npm run db:sync
 * ※ 冪等
 */

import fs from "fs";
import path from "path";
import { fileURLToPath } from "url";

const ROOT = path.join(path.dirname(fileURLToPath(import.meta.url)), "..");
const articlesPath = path.join(ROOT, "data", "articles.json");
const now = new Date().toISOString();

const TENT_URL = "https://store.alpen-group.jp/Form/Product/ProductList.aspx?cat=120001";
const CAMP_URL = "https://store.alpen-group.jp/Form/Product/ProductList.aspx?cat=120";

// slug -> [アンカー(この直後に挿入), 挿入する段落]
const EDITS = {
  "family-tent-ranking": [
    "- キャンプデビューの全体像 → [キャンプ初心者が揃えるべきギア一覧](/articles/camping-beginner-gear-checklist)",
    `\n\nなお、紹介した各テントは、アルペンアウトドアズ（スポーツデポ・アルペンの実店舗／オンライン）でも取り扱いがあります。実物を見てサイズ感や設営イメージを確かめてから決めたい方は、[アルペンアウトドアズのテント一覧](${TENT_URL})ものぞいてみてください。`,
  ],
  "winter-sleeping-bag-ranking": [
    "冬の静かなキャンプ場で、快適に眠れる夜を過ごしてくださいね。気になる商品があればぜひチェックしてみてください。",
    `\n\nシュラフは保温力の体感が大事なギアなので、実物を見て決めたい方も多いはず。アルペンアウトドアズ（スポーツデポ・アルペン）なら実店舗で寝袋を広げて確認できます。オンラインは[アルペンアウトドアズのキャンプ用品一覧](${CAMP_URL})からどうぞ。`,
  ],
};

const articles = JSON.parse(fs.readFileSync(articlesPath, "utf-8"));
let done = 0;
for (const [slug, [anchor, para]] of Object.entries(EDITS)) {
  const a = articles.find((x) => x.slug === slug);
  if (!a) { console.log(`⚠️ 記事なし: ${slug}`); continue; }
  if (a.content.includes("store.alpen-group.jp")) { console.log(`  ⏭️ 既存(アルペンリンク済): ${slug}`); continue; }
  if (!a.content.includes(anchor)) { console.log(`  ⚠️ アンカー無し: ${slug}`); continue; }
  a.content = a.content.replace(anchor, anchor + para);
  a.updatedAt = now;
  done++;
  console.log(`✅ アルペンリンク追加: ${slug}`);
}
fs.writeFileSync(articlesPath, JSON.stringify(articles, null, 2) + "\n", "utf-8");
console.log(`\n📝 ${done} 記事に追加。次に  npm run db:sync  で反映してください。`);
console.log("※ アルペンがLinkSwitch対応か、VCプログラム詳細(adDetail/2145165)で先に確認を。");
