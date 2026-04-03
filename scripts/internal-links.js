#!/usr/bin/env node

/**
 * 内部リンク最適化スクリプト
 * 記事間の関連性を分析し、内部リンクの追加を提案
 *
 * 分析基準:
 *   1. 同カテゴリ記事（最優先）
 *   2. 共通商品ID（商品が重複する記事）
 *   3. キーワード類似度（タイトル・excerpt・content内のキーワード重複）
 *
 * 使い方:
 *   node scripts/internal-links.js                 (分析 + 提案のみ)
 *   node scripts/internal-links.js --apply          (Markdown に内部リンクセクションを追加)
 *   node scripts/internal-links.js --slug=xxx       (特定記事のみ分析)
 */

import fs from "fs";
import path from "path";
import { fileURLToPath } from "url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const DATA_DIR = path.join(__dirname, "..", "data");

const APPLY = process.argv.includes("--apply");
const TARGET_SLUG = process.argv
  .find((a) => a.startsWith("--slug="))
  ?.split("=")[1];

// ============================================================
// データ読み込み
// ============================================================
const articles = JSON.parse(
  fs.readFileSync(path.join(DATA_DIR, "articles.json"), "utf-8")
).filter((a) => a.status === "published");

const categories = JSON.parse(
  fs.readFileSync(path.join(DATA_DIR, "categories.json"), "utf-8")
);

// ============================================================
// 既存の内部リンクを抽出
// ============================================================
function getExistingLinks(content) {
  const linkPattern = /\[.*?\]\(\/articles\/([\w-]+)\/?.*?\)/g;
  const links = new Set();
  let match;
  while ((match = linkPattern.exec(content)) !== null) {
    links.add(match[1]);
  }
  return links;
}

// ============================================================
// キーワード抽出（日本語対応の簡易版）
// ============================================================
function extractKeywords(text) {
  // カタカナ語、漢字語、英字語を抽出
  const patterns = [
    /[\u30A0-\u30FF]{2,}/g,      // カタカナ（2文字以上）
    /[\u4E00-\u9FFF]{2,}/g,      // 漢字（2文字以上）
    /[A-Za-z]{3,}/gi,             // 英字（3文字以上）
  ];

  const words = new Set();
  for (const pattern of patterns) {
    const matches = text.match(pattern) || [];
    matches.forEach((w) => words.add(w.toLowerCase()));
  }

  // ストップワード除外
  const stopWords = new Set([
    "おすすめ", "ランキング", "比較", "レビュー", "まとめ", "紹介",
    "こちら", "それぞれ", "ポイント", "チェック", "こちら",
    "the", "and", "for", "with", "from", "this", "that",
  ]);
  stopWords.forEach((w) => words.delete(w));

  return words;
}

// ============================================================
// 関連度スコア計算
// ============================================================
function calculateRelevance(articleA, articleB) {
  let score = 0;
  const reasons = [];

  // 1. 同カテゴリ（+30点）
  if (articleA.categoryId === articleB.categoryId) {
    score += 30;
    const cat = categories.find((c) => c.id === articleA.categoryId);
    reasons.push(`同カテゴリ(${cat?.name || articleA.categoryId})`);
  }

  // 2. 共通商品ID（1商品あたり+10点、最大30点）
  const commonProducts = articleA.productIds.filter((id) =>
    articleB.productIds.includes(id)
  );
  if (commonProducts.length > 0) {
    const productScore = Math.min(commonProducts.length * 10, 30);
    score += productScore;
    reasons.push(`共通商品${commonProducts.length}件`);
  }

  // 3. タイトルキーワード共通（1語あたり+5点、最大20点）
  const kwA = extractKeywords(articleA.title + " " + articleA.excerpt);
  const kwB = extractKeywords(articleB.title + " " + articleB.excerpt);
  const commonKw = [...kwA].filter((w) => kwB.has(w));
  if (commonKw.length > 0) {
    const kwScore = Math.min(commonKw.length * 5, 20);
    score += kwScore;
    reasons.push(`共通KW: ${commonKw.slice(0, 5).join(", ")}`);
  }

  // 4. コンテンツ内で相手記事のキーワードが出現（+10点）
  const titleWordsB = extractKeywords(articleB.title);
  const contentA = articleA.content || "";
  let contentMatch = 0;
  for (const w of titleWordsB) {
    if (w.length >= 3 && contentA.includes(w)) contentMatch++;
  }
  if (contentMatch >= 2) {
    score += 10;
    reasons.push(`本文内に関連語${contentMatch}語`);
  }

  return { score, reasons };
}

// ============================================================
// メイン分析
// ============================================================
function analyzeArticle(article) {
  const existingLinks = getExistingLinks(article.content || "");
  const suggestions = [];

  for (const other of articles) {
    if (other.id === article.id) continue;

    const { score, reasons } = calculateRelevance(article, other);
    const alreadyLinked = existingLinks.has(other.slug);

    if (score >= 20) {
      suggestions.push({
        slug: other.slug,
        title: other.title,
        score,
        reasons,
        alreadyLinked,
      });
    }
  }

  // スコア順でソート
  suggestions.sort((a, b) => b.score - a.score);

  return {
    article,
    existingLinks: [...existingLinks],
    suggestions,
    missingLinks: suggestions.filter((s) => !s.alreadyLinked),
  };
}

// ============================================================
// 関連記事セクションをMarkdownに追加
// ============================================================
function addRelatedSection(article, suggestions) {
  const top = suggestions
    .filter((s) => !s.alreadyLinked)
    .slice(0, 3);

  if (top.length === 0) return null;

  const section = `\n\n## 関連記事\n\n${top
    .map((s) => `- [${s.title}](/articles/${s.slug})`)
    .join("\n")}\n`;

  // 既に関連記事セクションがあれば置換、なければ末尾に追加
  let content = article.content || "";
  if (content.includes("## 関連記事")) {
    content = content.replace(
      /\n## 関連記事\n[\s\S]*?(?=\n## |$)/,
      section
    );
  } else {
    content += section;
  }

  return content;
}

// ============================================================
// 実行
// ============================================================
function main() {
  const targetArticles = TARGET_SLUG
    ? articles.filter((a) => a.slug === TARGET_SLUG)
    : articles;

  if (targetArticles.length === 0) {
    console.log("❌ 対象記事が見つかりません");
    process.exit(1);
  }

  console.log(`\n🔗 内部リンク最適化分析`);
  console.log(`  対象: ${targetArticles.length}記事\n`);

  const allResults = [];
  let totalMissing = 0;

  for (const article of targetArticles) {
    const result = analyzeArticle(article);
    allResults.push(result);

    const cat = categories.find((c) => c.id === article.categoryId);
    console.log(`━━━ ${article.title.slice(0, 50)} ━━━`);
    console.log(`  カテゴリ: ${cat?.name || article.categoryId}`);
    console.log(`  既存リンク: ${result.existingLinks.length}件 [${result.existingLinks.join(", ")}]`);

    if (result.missingLinks.length > 0) {
      console.log(`  📝 追加推奨リンク:`);
      result.missingLinks.slice(0, 5).forEach((s) => {
        console.log(
          `    ${s.alreadyLinked ? "✅" : "➕"} [スコア${s.score}] ${s.title}`
        );
        console.log(`       理由: ${s.reasons.join(" / ")}`);
      });
      totalMissing += result.missingLinks.length;
    } else {
      console.log(`  ✅ 追加推奨なし`);
    }
    console.log("");
  }

  // サマリー
  console.log(`\n━━━ サマリー ━━━`);
  console.log(`  分析記事数: ${targetArticles.length}`);
  console.log(`  追加推奨リンク: ${totalMissing}件`);

  // 相互リンク不足の検出
  const missingMutual = [];
  for (const result of allResults) {
    for (const suggestion of result.missingLinks.filter((s) => s.score >= 30)) {
      const reverse = allResults.find(
        (r) => r.article.slug === suggestion.slug
      );
      if (reverse) {
        const reverseLinked = reverse.existingLinks.includes(
          result.article.slug
        );
        if (!reverseLinked) {
          missingMutual.push({
            a: result.article.slug,
            b: suggestion.slug,
            score: suggestion.score,
          });
        }
      }
    }
  }

  if (missingMutual.length > 0) {
    console.log(`\n  ⚠️ 相互リンク不足（両方向ともリンクなし）:`);
    const seen = new Set();
    missingMutual.forEach((m) => {
      const key = [m.a, m.b].sort().join("<->");
      if (!seen.has(key)) {
        seen.add(key);
        console.log(`    ${m.a} ↔ ${m.b} (スコア${m.score})`);
      }
    });
  }

  // --apply モード
  if (APPLY) {
    console.log(`\n\n📝 関連記事セクションを追加中...\n`);
    let updated = 0;

    const allArticles = JSON.parse(
      fs.readFileSync(path.join(DATA_DIR, "articles.json"), "utf-8")
    );

    for (const result of allResults) {
      const newContent = addRelatedSection(
        result.article,
        result.suggestions
      );
      if (newContent) {
        const idx = allArticles.findIndex((a) => a.id === result.article.id);
        if (idx >= 0) {
          allArticles[idx].content = newContent;
          allArticles[idx].updatedAt = new Date().toISOString();
          updated++;
          console.log(`  ✅ ${result.article.slug} — 関連記事セクション追加`);
        }
      }
    }

    if (updated > 0) {
      fs.writeFileSync(
        path.join(DATA_DIR, "articles.json"),
        JSON.stringify(allArticles, null, 2),
        "utf-8"
      );
      console.log(`\n✅ ${updated}記事を更新しました`);
    } else {
      console.log(`\nℹ️ 更新が必要な記事はありませんでした`);
    }
  } else {
    console.log(`\n💡 リンクを自動追加するには --apply オプションを使用してください`);
    console.log(`   node scripts/internal-links.js --apply`);
  }

  // レポートJSONを保存
  const report = allResults.map((r) => ({
    slug: r.article.slug,
    title: r.article.title,
    category: r.article.categoryId,
    existingLinks: r.existingLinks.length,
    missingLinks: r.missingLinks.length,
    topSuggestions: r.missingLinks.slice(0, 5).map((s) => ({
      slug: s.slug,
      score: s.score,
      reasons: s.reasons,
    })),
  }));

  fs.writeFileSync(
    path.join(DATA_DIR, "internal-links-report.json"),
    JSON.stringify(report, null, 2),
    "utf-8"
  );
  console.log(`\n📄 レポート保存: data/internal-links-report.json`);
}

main();
