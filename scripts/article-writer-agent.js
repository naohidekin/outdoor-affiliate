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

// 記事本文は脱AI・体温注入が最重要のため Opus 4.8 を既定にする（収益源・本数少で増分は月数百円）。
// ARTICLE_WRITER_MODEL で上書き可能。キー未対応で 404 の場合は下記へ自動フォールバック。
const MODEL = process.env.ARTICLE_WRITER_MODEL || "claude-opus-4-8";
const MODEL_FALLBACK = process.env.ARTICLE_WRITER_FALLBACK_MODEL || "claude-sonnet-4-6";
const MAX_RETRIES = 1;

// model が 404(not_found)なら 1 度だけフォールバックモデルで再試行するラッパー。
// 週次自動実行が Opus 未対応キーで静かに止まるのを防ぐ。
async function createWithModelFallback(client, params) {
  try {
    return await client.messages.create(params);
  } catch (err) {
    const notFound = err?.status === 404 || /not_found|model:/i.test(err?.message || "");
    if (notFound && params.model !== MODEL_FALLBACK) {
      console.warn(`[article-writer] モデル ${params.model} が404 → ${MODEL_FALLBACK} へフォールバック`);
      return await client.messages.create({ ...params, model: MODEL_FALLBACK });
    }
    throw err;
  }
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
  const opts = { dryRun: false, themeIndex: null, retryArticleId: null, feedbackJson: null };
  for (let i = 0; i < args.length; i++) {
    switch (args[i]) {
      case "--dry-run":      opts.dryRun = true; break;
      case "--theme-index":  opts.themeIndex = parseInt(args[++i], 10); break;
      case "--retry":        opts.retryArticleId = args[++i]; break;
      case "--feedback-json":
        try {
          opts.feedbackJson = JSON.parse(args[++i] || "{}");
        } catch {
          opts.feedbackJson = null;
        }
        break;
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

function loadWiseSkill() {
  try {
    return fs.readFileSync(path.join(PROJECT_ROOT, "SKILL.md"), "utf-8");
  } catch {
    return "";
  }
}

// ─── 品質スコア計算 ──────────────────────────────────

const SCORING_CRITERIA = [
  "ギア男ボイス（ですます調・友人目線の温かさ・断言一辺倒にしない。NGワードなし）",
  "構成完成度（リード→選び方→ランキング→比較表→FAQ→まとめ）",
  "SEO適合（タイトル・見出しにキーワード含有、metaDescription160文字以内）",
  "商品情報正確性（スペック・価格がデータと一致）",
  "比較の公平性（各商品の強み弱みを記述）",
  "読者価値（初心者〜中級者が選び方を理解できる）",
  "CTA適切さ（押しつけがましくない誘導）",
  "文字数適正（2000〜4000文字、最低2000文字必須）",
  "内部リンク（同カテゴリ既存記事への自然なリンクが2〜3箇所）",
  "FAQ充実度（読者が検索しそうな質問3〜5問と的確な回答）",
  "センス（読者の半歩先を行く提案・文章の品格と洗練度・camp-gear-labの世界観・具体的で記憶に残る言葉選び）",
];

async function scoreArticle(anthropic, content, theme) {
  try {
    const response = await anthropic.messages.create({
      model: process.env.ARTICLE_SCORER_MODEL || "claude-sonnet-4-6",
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

function getRelatedArticleSlugs(categoryId, allArticles) {
  return allArticles
    .filter((a) => a.status === "published" && a.categoryId === categoryId)
    .map((a) => ({ slug: a.slug, title: a.title }))
    .slice(0, 5);
}

function getWordCountTarget(formatRecommendation) {
  return {
    ranking: "5000〜8000字",
    comparison: "5000〜8000字",
    guide: "3000〜5000字",
    "how-to": "3000〜5000字",
    review: "2000〜3500字",
  }[formatRecommendation] || "3000〜5000字";
}

async function generateArticle(anthropic, theme, products, analystFeedback, guidelines, allArticles, wiseFeedback = null) {
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

  const relatedArticles = getRelatedArticleSlugs(theme.categoryId, allArticles || []);
  const internalLinkSection = relatedArticles.length > 0
    ? `\n内部リンク候補（同カテゴリの既存記事）:\n${relatedArticles.map((a) => `- [${a.title}](/articles/${a.slug})`).join("\n")}\n記事内に2〜3箇所、自然な文脈で上記記事へのリンクを入れてください。`
    : "";
  const wiseFeedbackSection = wiseFeedback
    ? `\n前回レビュー（wise_scores）:\n${JSON.stringify(wiseFeedback, null, 2)}\n不足スコアを優先改善してください。`
    : "";
  const supervisorFeedbackSection = Array.isArray(wiseFeedback?.feedback) && wiseFeedback.feedback.length
    ? `\nSupervisor指摘:\n- ${wiseFeedback.feedback.join("\n- ")}\n指摘を解消してください。`
    : "";
  const wordCountTarget = getWordCountTarget(theme.format_recommendation);
  const amazonTag = process.env.AMAZON_PARTNER_TAG;
  if (!amazonTag) {
    throw new Error("AMAZON_PARTNER_TAG 未設定（例: cmap78-22）");
  }

  const systemPrompt = `あなたはアウトドア・キャンプ用品アフィリエイトサイト「camp-gear-lab.com」の記事ライターです。
ペルソナ「ギア男」として記事を書きます。

${guidelines}
${loadWiseSkill()}
${feedbackSection}
${wiseFeedbackSection}
${supervisorFeedbackSection}

【AFFILIATE_RULES（必須）】
- 比較/ランキング記事は {{comparison:${products.map((p) => p.id).join(",")}}} を必ず含める
- Amazonボタンを含める（AMAZON_PARTNER_TAG=${amazonTag || "未設定"} を参照し、ハードコード禁止）
- 楽天ボタンを含める（全商品対象）
- 内部リンクを /articles/[slug] 形式で2〜3本入れる

重要ルール:
- 商品へのリンクは文中に自然に入れる（アフィリエイトURLは使わず、本文内では「気になる方はチェックを」程度）
- Markdown形式で出力する
- ${wordCountTarget} を目安にする
${internalLinkSection}`;

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
2. 「この記事の答え」ボックス: リード直後に > 引用ブロックで、記事全体の結論を40〜60字で即答する（AI検索・ゼロクリック対策の要。例: > **結論**: ファミリーなら◯◯が最適。理由は△△と□□。予算重視なら××。）
3. ${theme.categoryId}を選ぶポイント（2-3項目）
4. おすすめランキング TOP3（各商品の特徴・良い点・注意点）
5. スペック比較表（{{comparison:id1,id2,id3}} タグ）
6. よくある質問（FAQ 3〜5問。読者が検索しそうな疑問に回答）
7. まとめ（結論の再掲 + CTA）

AIO（AI検索最適化）ルール:
- H2見出しはできるだけ読者の検索質問そのままの疑問形にする（例: 「◯◯はどれを選べばいい？」「△△と□□はどっちがいい？」）
- 疑問形H2の直後の1段落（40〜60字）で必ず先に答えを言い切り、その後に理由・詳細を書く（結論→根拠の順を徹底）
- 比較・数値は表形式で示す（AIは表を引用しやすい）
- 曖昧な「〜かもしれません」ではなく、条件付きの断定で書く（「子連れなら◯◯一択です」）

併せて以下のメタ情報も JSON で返してください（記事本文の後に --- 区切りで）:
{
  "excerpt": "120文字以内の記事要約",
  "metaDescription": "160文字以内のSEOメタディスクリプション。テーマのキーワードを含め、クリックしたくなる説明文",
  "tags": ["タグ1", "タグ2"],
  "faqs": [
    {"question": "質問1", "answer": "回答1"},
    {"question": "質問2", "answer": "回答2"},
    {"question": "質問3", "answer": "回答3"}
  ]
}`;

  console.log("[article-writer] Claude API 呼び出し中...");

  const response = await createWithModelFallback(anthropic, {
    model: MODEL,
    max_tokens: 8000,
    messages: [{ role: "user", content: userPrompt }],
    system: systemPrompt,
  });

  const fullText = response.content[0].text.trim();

  // 本文とメタ情報を分離（記事本文にも --- が含まれるため、最後の --- のみで分割）
  let content = fullText;
  let meta = { excerpt: "", metaDescription: "", tags: [], faqs: [] };

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
  } else {
    // ---セパレータなしでコードフェンスJSONが末尾に来た場合
    const fencedJsonMatch = fullText.match(/([\s\S]*?)\n```json\s*\n(\{[\s\S]*?\})\s*```\s*$/);
    if (fencedJsonMatch) {
      content = fencedJsonMatch[1].trim();
      try {
        meta = JSON.parse(fencedJsonMatch[2].trim());
      } catch {
        console.warn("[article-writer] メタ情報のパースに失敗（コードフェンス形式）");
      }
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

  // リトライモード: 既存記事を再生成して上書き
  if (opts.retryArticleId) {
    let articles = readJson("articles.json") || [];
    const targetIdx = articles.findIndex((a) => a.id === opts.retryArticleId);
    if (targetIdx === -1) {
      console.error(`[article-writer] 記事 ${opts.retryArticleId} が見つかりません`);
      process.exit(1);
    }
    const target = articles[targetIdx];
    if (target.status === "published") {
      console.error("[article-writer] published 記事は --retry で更新できません");
      process.exit(1);
    }
    console.log(`[article-writer] リトライ: ${target.title}`);

    const allProducts = readJson("products.json") || [];
    const products = (target.productIds || [])
      .map((id) => allProducts.find((p) => p.id === id))
      .filter(Boolean);

    if (products.length === 0) {
      console.error("[article-writer] リトライ対象の商品データがありません");
      process.exit(1);
    }

    const { content, meta } = await generateArticle(
      anthropic, target, products, analystFeedback, guidelines, articles, opts.feedbackJson || null
    );
    const scoring = await scoreArticle(anthropic, content, target);
    console.log(`[article-writer] リトライスコア: ${scoring.total.toFixed(1)}`);

    if (!opts.dryRun) {
      articles[targetIdx] = {
        ...target,
        content,
        excerpt: meta?.excerpt || target.excerpt,
        metaDescription: meta?.metaDescription || target.metaDescription,
        faqs: meta?.faqs?.length > 0 ? meta.faqs : target.faqs,
        qualityScore: scoring.total,
        updatedAt: jstIsoString(),
        generationMeta: {
          ...target.generationMeta,
          retryCount: (target.generationMeta?.retryCount || 0) + 1,
          generatedAt: jstIsoString(),
        },
      };
      writeJson("articles.json", articles);
      console.log("[article-writer] articles.json を更新しました");
    } else {
      console.log(`[DRY RUN] スコア: ${scoring.total.toFixed(1)}\n${content.slice(0, 300)}...`);
    }
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
        anthropic, theme, products, analystFeedback, guidelines, articles, opts.feedbackJson || null
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
    const now = jstIsoString();

    const article = {
      id: uuidv4(),
      title: theme.title,
      slug: theme.slug,
      categoryId: theme.categoryId,
      content: bestContent,
      excerpt: bestMeta?.excerpt || "",
      productIds: productIds,
      status: "draft",
      faqs: bestMeta?.faqs || [],
      metaDescription: bestMeta?.metaDescription || "",
      tags: bestMeta?.tags || [],
      createdAt: now,
      updatedAt: now,
      publishedAt: null,
      autoGenerated: true,
      qualityScore: bestScore,
      // 2026-07-11 棚卸監査の決定: 週次工場は「下書き止まり」。
      // 公開予定日は人間が管理画面で仕上げ後に設定する（無人公開の封印）。
      // 自動公開に戻す場合は theme.scheduledPublishDate を再度セットすること。
      scheduledPublishDate: null,
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
