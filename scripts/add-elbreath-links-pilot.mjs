#!/usr/bin/env node

/**
 * エルブレス(L-Breath / ゼビオグループ / ValueCommerce)導線パイロット。
 * エルブレスは supersports.com ドメイン = 既に計測登録済み(valuecommerce) & LinkSwitch対応。
 * よって直リンクを貼るだけでクリック時に自動アフィリンク化される(報酬6.28%)。
 * ※アルペンはMyLink専用で自動変換されないため、こちらに差し替えた。
 * 使い方: node scripts/add-elbreath-links-pilot.mjs  →  npm run db:sync
 * ※ 冪等
 */

import fs from "fs";
import path from "path";
import { fileURLToPath } from "url";

const ROOT = path.join(path.dirname(fileURLToPath(import.meta.url)), "..");
const articlesPath = path.join(ROOT, "data", "articles.json");
const now = new Date().toISOString();

const TENT_URL = "https://www.supersports.com/ja-jp/lbreath/categories/outdoor-camping/tent/";
const SHRAF_URL = "https://www.supersports.com/ja-jp/lbreath/categories/outdoor-camping/shraf-pillow/";

// slug -> [アンカー(この直後に挿入), 挿入する段落]
const EDITS = {
  "family-tent-ranking": [
    "- キャンプデビューの全体像 → [キャンプ初心者が揃えるべきギア一覧](/articles/camping-beginner-gear-checklist)",
    `\n\nなお、紹介した各テントは、アウトドア専門店の[エルブレス（ゼビオグループ）のテント一覧](${TENT_URL})でも取り扱いがあります。実物を見てサイズ感や設営イメージを確かめたい方は、店舗受け取りもできるのでのぞいてみてください。`,
  ],
  "winter-sleeping-bag-ranking": [
    "冬の静かなキャンプ場で、快適に眠れる夜を過ごしてくださいね。気になる商品があればぜひチェックしてみてください。",
    `\n\nシュラフは保温力の体感が大事なギアなので、実物を見て決めたい方も多いはず。アウトドア専門店の[エルブレス（ゼビオグループ）のシュラフ一覧](${SHRAF_URL})なら、NANGA・モンベル・イスカなど主要ブランドを実店舗でも確認できます。`,
  ],
};

const articles = JSON.parse(fs.readFileSync(articlesPath, "utf-8"));
let done = 0;
for (const [slug, [anchor, para]] of Object.entries(EDITS)) {
  const a = articles.find((x) => x.slug === slug);
  if (!a) { console.log(`⚠️ 記事なし: ${slug}`); continue; }
  if (a.content.includes("supersports.com/ja-jp/lbreath")) { console.log(`  ⏭️ 既存(エルブレスリンク済): ${slug}`); continue; }
  // 万一アルペン直リンクが入っていたら除去（MyLink専用で機能しないため）
  a.content = a.content.replace(/\n\nなお、紹介した各テント[^\n]*store\.alpen-group\.jp[^\n]*。/g, "");
  a.content = a.content.replace(/\n\nシュラフは保温力[^\n]*store\.alpen-group\.jp[^\n]*。/g, "");
  if (!a.content.includes(anchor)) { console.log(`  ⚠️ アンカー無し: ${slug}`); continue; }
  a.content = a.content.replace(anchor, anchor + para);
  a.updatedAt = now;
  done++;
  console.log(`✅ エルブレスリンク追加: ${slug}`);
}
fs.writeFileSync(articlesPath, JSON.stringify(articles, null, 2) + "\n", "utf-8");
console.log(`\n📝 ${done} 記事に追加。次に  npm run db:sync  で反映してください。`);
console.log("※ supersports.comは計測済み＆LinkSwitch対応。直リンクでも自動アフィリンク化されます。");
