#!/usr/bin/env node

/**
 * Article Writer Agent — 記事本文生成（Claude API）
 *
 * article-weekly-plan.json の各テーマに対して記事本文を生成し、
 * articles.json に draft ステータスで追加する。
 * Publisher Agent が qualityScore と scheduledPublishDate に基づいて公開を判定する。
 *
 * 使い方:
 *   node scripts/article-writer-agent.js                   # 全テーマの記事生成
 *   node scripts/article-writer-agent.js --dry-run         # 表示のみ
 *   node scripts/article-writer-agent.js --theme-index 0   # 特定テーマのみ
 *   node scripts/article-writer-agent.js --retry article-id # リトライ
 */

import Anthropic from "@anthropic-ai/sdk";
import { v4 as uuidv4 } from "uuid";
import {
  loadEnv,
  readJson,
  writeJson,
  checkArticleKillSwitch,
} from "../src/lib/x-agent-utils.mjs";
import fs from "fs";
import path from "path";
import { fileURLToPath } from "url";

loadEnv();

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const PROJECT_ROOT = path.join(__dirname, "..");

const MODEL = process.env.ARTICLE_WRITER_MODEL || "claude-sonnet-4-6";
const MAX_RETRIES = 1;

// ─── CLI ─────────────────────────────────────────────

function parseArgs() {
  const args = process.argv.slice(2);
  const opts = { dryRun: false, themeIndex: null, retryArticleId: null };
  for (let i = 0; i < args.length; i++) {
    switch (args[i]) {
      case "--dry-run":      opts.dryRun = true; break;
      case "--theme-index":  opts.themeIndex = parseInt(args[++i], 10); break;
      case "--retry":        opts.retryArticleId = args[++i]; break;
    }
  }
  return opts;
}

// ─── CLAUDE.md から記事ガイドライン読み込み ──────────

function loadWritingGuidelines() {
  try {
    const claudeMd = fs.readFileSync(path.join(PROJECT_ROOT, "CLAUDE.md"), "utf-8");
    // 記事執筆ガイドラインセクションを抽出
    const match = claudeMd.match(/# 記事執筆ガイドライン[\s\S]*?(?=\n# [^#]|$)/);
    return match ? match[0] : "";
  } catch {
    return "";
  }
}

// ─── 品質スコア計算 ──────────────────────────────────

const SCORING_CRITERIA = [
  "ギア男ボイス（断言型・淡々・知的。NGワードなし）",
  "構成完成度（リード→選び方→ランキング→比較表→まとめ）",
  "SEO適合（タイトル・見出しにキーワード含有）",
  "商品情報正確性（スペック・価格がデータと一致）",
  "比較の公平性（各商品の強み弱みを記述）",
  "読者価値（初心者〜中級者が選び方を理解できる）",
  "CTA適切さ（押しつけがましくない誘導）",
  "文字数適正（2000〜4000文字）",
  "オリジナリティ（既存記事と切り口が異なる）",
  "メタ情報（excerpt・metaDescription・tagsが適切）",
];

async function scoreArticle(anthropic, content, theme) {
  try {
    const response = await anthropic.messages.create({
      model: process.env.ARTICLE_SCORER_MODEL || "claude-haiku-4-5-20251001",
      max_tokens: 500,
      messages: [{
        role: "user",
        content: `以下の記事を10項目で採点してください（各1〜10点）。

採点項目:
${SCORING_CRITERIA.map((c, i) => `${i + 1}. ${c}`).join("\n")}

記事テーマ: ${theme.title}
記事本文（冒頭2000文字）:
${content.slice(0, 2000)}

JSONのみで返してください:
{"scores": [点数1, 点数2, ...], "total": 合計/10の平均, "notes": "一言コメント"}`,
      }],
    });

    const text = response.content[0].text.trim();
    // JSON部分を抽出（前後にテキストが付く場合に対応）
    const jsonMatch = text.match(/\{[\s\S]*\}/);
    if (!jsonMatch) throw new Error("JSONが見つかりません");
    const result = JSON.parse(jsonMatch[0]);
    return {
      scores: result.scores || [],
      total: Number(result.total) || 0,
      notes: result.notes || "",
    };
  } catch (err) {
    console.warn(`[article-writer] 採点エラー: ${err.message}`);
    return { scores: [], total: 5.0, notes: "採点エラー" };
  }
}

// ─── 記事生成 ────────────────────────────────────────

async function generateArticle(anthropic, theme, products, analystFeedback, guidelines) {
  const productInfo = products.map((p, i) => `
### 商品${i + 1}: ${p.name}
- ブランド: ${p.brand}
- 価格: ¥${p.price.toLocaleString()}
- スペック: ${JSON.stringify(p.specs)}
- products.json ID: ${p.id}
- 評価: ${p.rating}/5
`).join("\n");

  const feedbackSection = analystFeedback?.effectivePatterns?.length > 0
    ? `\n過去の高パフォーマンス記事パターン:\n${analystFeedback.effectivePatterns.join("\n")}`
    : "";

  const systemPrompt = `あなたはアウトドア・キャンプ用品アフィリエイトサイト「camp-gear-lab.com」の記事ライターです。
ペルソナ「ギア男」として記事を書きます。

${guidelines}
${feedbackSection}

重要ルール:
- 比較表は {{comparison:${products.map((p) => p.id).join(",")}}} タグを使う
- 商品へのリンクは文中に自然に入れる（アフィリエイトURLは使わず、本文内では「気になる方はチェックを」程度）
- Markdown形式で出力する
- 2000〜4000文字を目安にする`;

  const userPrompt = `以下のテーマで記事を生成してください。

テーマ: ${theme.title}
切り口: ${theme.angle}
ターゲットキーワード: ${theme.targetKeywords?.join(", ")}
季節コンテキスト: ${theme.seasonRelevance || "通年"}
カテゴリ: ${theme.categoryId}

使用商品データ:
${productInfo}

記事構成:
1. リード文（結論ファースト、2-3文）
2. ${theme.categoryId}を選ぶポイント（2-3項目）
3. おすすめランキング TOP3（各商品の特徴・良い点・注意点）
4. スペック比較表（{{comparison:id1,id2,id3}} タグ）
5. まとめ（結論の再掲 + CTA）

併せて以下のメタ情報も JSON で返してください（記事本文の後に --- 区切りで）:
{"excerpt": "...", "metaDescription": "...", "tags": ["...", "..."]}`;

  console.log("[article-writer] Claude API 呼び出し中...");

  const response = await anthropic.messages.create({
    model: MODEL,
    max_tokens: 8000,
    messages: [{ role: "user", content: userPrompt }],
    system: systemPrompt,
  });

  const fullText = response.content[0].text.trim();

  // 本文とメタ情報を分離（記事本文にも --- が含まれるため、最後の --- のみで分割）
  let content = fullText;
  let meta = { excerpt: "", metaDescription: "", tags: [] };

  // 末尾のJSON部分を検出（最後の { から } まで）
  const lastJsonMatch = fullText.match(/\n---\s*\n([\s\S]*?\{[\s\S]*\})\s*$/);
  if (lastJsonMatch) {
    content = fullText.slice(0, fullText.lastIndexOf("\n---")).trim();
    try {
      const metaStr = lastJsonMatch[1].trim()
        .replace(/^```json?\s*/, "").replace(/\s*```$/, "");
      meta = JSON.parse(metaStr);
    } catch {
      console.warn("[article-writer] メタ情報のパースに失敗（デフォルト使用）");
    }
  }

  return { content, meta };
}

// ─── メイン ──────────────────────────────────────────

async function main() {
  const opts = parseArgs();

  const ks = checkArticleKillSwitch();
  if (ks.killed) {
    console.error(`[article-writer] ${ks.reason}`);
    process.exit(1);
  }

  const anthropic = new Anthropic();
  const guidelines = loadWritingGuidelines();
  const analystFeedback = readJson("article-analyst-feedback.json");

  // リトライモード
  if (opts.retryArticleId) {
    const articles = readJson("articles.json") || [];
    const target = articles.find((a) => a.id === opts.retryArticleId);
    if (!target) {
      console.error(`[article-writer] 記事 ${opts.retryArticleId} が見つかりません`);
      process.exit(1);
    }
    console.log(`[article-writer] リトライ: ${target.title}`);
    // リトライロジックは通常生成と同じフローで再生成
    // ここでは省略（フルパイプラインで使用）
    return;
  }

  const plan = readJson("article-weekly-plan.json");
  if (!plan || !plan.articles) {
    console.error("[article-writer] article-weekly-plan.json がないか空です");
    process.exit(1);
  }

  const allProducts = readJson("products.json") || [];
  let articles = readJson("articles.json") || [];

  const themes = opts.themeIndex != null
    ? [plan.articles[opts.themeIndex]].filter(Boolean)
    : plan.articles;

  console.log(`[article-writer] ${themes.length}記事の生成を開始`);

  for (const theme of themes) {
    console.log(`\n${"═".repeat(60)}`);
    console.log(`[article-writer] 生成中: ${theme.title}`);
    console.log(`${"═".repeat(60)}`);

    // テーマに紐づく商品を取得
    const productIds = theme.productIds || [];
    const products = productIds
      .map((id) => allProducts.find((p) => p.id === id))
      .filter(Boolean);

    if (products.length === 0) {
      console.warn("[article-writer] 商品データがありません。スキップ。");
      continue;
    }

    let bestContent = null;
    let bestMeta = null;
    let bestScore = 0;
    let retryCount = 0;

    for (let attempt = 0; attempt <= MAX_RETRIES; attempt++) {
      const { content, meta } = await generateArticle(
        anthropic, theme, products, analystFeedback, guidelines
      );

      const scoring = await scoreArticle(anthropic, content, theme);
      console.log(`[article-writer] スコア: ${scoring.total.toFixed(1)} (attempt ${attempt + 1})`);

      if (scoring.total > bestScore) {
        bestScore = scoring.total;
        bestContent = content;
        bestMeta = meta;
        retryCount = attempt;
      }

      // スコア >= 7.0 ならリトライ不要
      if (scoring.total >= 7.0) break;

      if (attempt < MAX_RETRIES) {
        console.log("[article-writer] スコア不足。リトライ...");
      }
    }

    // Fix 1: Writer は常に draft。Publisher が qualityScore + scheduledPublishDate で公開判定する
    const now = new Date().toISOString();

    const article = {
      id: uuidv4(),
      title: theme.title,
      slug: theme.slug,
      categoryId: theme.categoryId,
      content: bestContent,
      excerpt: bestMeta?.excerpt || "",
      productIds: productIds,
      status: "draft",
      faqs: [],
      metaDescription: bestMeta?.metaDescription || "",
      tags: bestMeta?.tags || [],
      createdAt: now,
      updatedAt: now,
      publishedAt: null,
      autoGenerated: true,
      qualityScore: bestScore,
      scheduledPublishDate: theme.scheduledPublishDate,
      generationMeta: {
        themeId: theme.themeId,
        model: MODEL,
        retryCount,
        generatedAt: now,
      },
    };

    console.log(`[article-writer] → ${article.title}`);
    console.log(`  スコア: ${bestScore.toFixed(1)} / ステータス: draft`);
    console.log(`  文字数: ${bestContent.length}`);

    if (opts.dryRun) {
      console.log("[DRY RUN] articles.json への書き込みをスキップ");
      console.log(`\n--- 生成記事プレビュー (冒頭500文字) ---\n${bestContent.slice(0, 500)}...\n`);
    } else {
      articles.push(article);
      writeJson("articles.json", articles);
      console.log("[article-writer] articles.json に追加しました");
    }
  }

  console.log("\n[article-writer] 記事生成完了");
}

main().catch((err) => {
  console.error("[article-writer] エラー:", err.message);
  process.exit(1);
});
