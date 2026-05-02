#!/usr/bin/env node
/**
 * ドラフト記事に内部リンク（関連記事セクション）を自動追加するスクリプト
 *
 * 使い方:
 *   node scripts/add-internal-links-to-drafts.js           (全ドラフト)
 *   node scripts/add-internal-links-to-drafts.js --dry-run  (確認のみ)
 *   node scripts/add-internal-links-to-drafts.js --slug=xxx  (1件のみ)
 */

import fs from "fs";
import path from "path";
import { fileURLToPath } from "url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const DATA_DIR = path.join(__dirname, "..", "data");
const DRY_RUN = process.argv.includes("--dry-run");
const TARGET_SLUG = process.argv.find((a) => a.startsWith("--slug="))?.split("=")[1];

// ============================================================
// データ読み込み
// ============================================================
const articles = JSON.parse(fs.readFileSync(path.join(DATA_DIR, "articles.json"), "utf-8"));
const published = articles.filter((a) => a.status === "published");
const drafts = articles.filter((a) => a.status === "draft" && (!TARGET_SLUG || a.slug === TARGET_SLUG));

// ============================================================
// キーワード抽出（簡易版）
// ============================================================
function extractKeywords(text = "") {
  const patterns = [
    /[\u30A0-\u30FF]{2,}/g,
    /[\u4E00-\u9FFF]{2,}/g,
    /[A-Za-z]{3,}/gi,
  ];
  const words = new Set();
  for (const pattern of patterns) {
    (text.match(pattern) || []).forEach((w) => words.add(w.toLowerCase()));
  }
  const stopWords = new Set([
    "おすすめ", "ランキング", "比較", "レビュー", "まとめ", "紹介",
    "こちら", "それぞれ", "ポイント", "チェック", "the", "and", "for", "with",
  ]);
  stopWords.forEach((w) => words.delete(w));
  return words;
}

// ============================================================
// スコア計算: 共通キーワード数（タイトル + excerpt）
// ============================================================
function calcScore(draft, candidate) {
  const draftKw = extractKeywords(`${draft.title} ${draft.excerpt || ""}`);
  const candKw = extractKeywords(`${candidate.title} ${candidate.excerpt || ""}`);
  const common = [...draftKw].filter((w) => candKw.has(w));

  // カテゴリが同じなら加点
  const sameCategory = draft.categoryId && draft.categoryId === candidate.categoryId ? 10 : 0;
  return common.length * 5 + sameCategory;
}

// ============================================================
// メイン処理
// ============================================================
let updated = false;

for (const draft of drafts) {
  const hasLink = (draft.content || "").includes("/articles/");
  if (hasLink) {
    console.log(`[skip] ${draft.slug}: 既に内部リンクあり`);
    continue;
  }

  // スコア計算して上位3件取得（同slugは除外）
  const candidates = published
    .filter((a) => a.slug !== draft.slug)
    .map((a) => ({ article: a, score: calcScore(draft, a) }))
    .filter(({ score }) => score > 0)
    .sort((a, b) => b.score - a.score)
    .slice(0, 3);

  if (candidates.length === 0) {
    console.warn(`[warn] ${draft.slug}: 関連記事が見つかりません`);
    continue;
  }

  console.log(`\n[${draft.slug}] 内部リンク追加:`);
  candidates.forEach(({ article, score }) => {
    console.log(`  + [スコア${score}] ${article.title}`);
  });

  if (!DRY_RUN) {
    // 本文末尾に関連記事セクションを追加
    const relatedSection =
      "\n\n---\n\n## 関連記事\n\n" +
      candidates
        .map(({ article }) => `- [${article.title}](/articles/${article.slug})`)
        .join("\n");

    const idx = articles.findIndex((a) => a.slug === draft.slug);
    articles[idx].content = (articles[idx].content || "") + relatedSection;
    updated = true;
    console.log(`  → 本文末尾に「関連記事」セクションを追加しました`);
  } else {
    console.log(`  → [DRY RUN] スキップ`);
  }
}

if (updated) {
  fs.writeFileSync(path.join(DATA_DIR, "articles.json"), JSON.stringify(articles, null, 2));
  console.log("\n✅ articles.json を更新しました");
} else if (!DRY_RUN) {
  console.log("\n（更新なし）");
}
