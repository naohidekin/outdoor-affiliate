#!/usr/bin/env node

/**
 * Article Analyst Agent — 記事パフォーマンス分析・Writerへのフィードバック生成
 *
 * GA4 + affiliate-clicks.json から記事PV・クリック率を分析し、
 * article-analyst-feedback.json を通じて Researcher / Writer にフィードバックを渡す。
 *
 * 使い方:
 *   node scripts/article-analyst-agent.js                # 28日分析、feedback更新
 *   node scripts/article-analyst-agent.js --dry-run      # 表示のみ（書き込みなし）
 *   node scripts/article-analyst-agent.js --days 7       # 分析期間指定
 */

import Anthropic from "@anthropic-ai/sdk";
import {
  loadEnv,
  readJson,
  writeJson,
  checkArticleKillSwitch,
} from "../src/lib/x-agent-utils.mjs";

loadEnv();

// googleapis は巨大で環境によっては import だけでハングするため、GA4 を実際に
// 呼ぶ時だけ遅延ロード（import・API呼び出しにタイムアウトを掛ける）。
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

async function generateEffectivePatterns(topArticles, articles) {
  try {
    const apiKey = process.env.ANTHROPIC_API_KEY;
    if (!apiKey || !topArticles?.length) return [];
    const client = new Anthropic({ apiKey });
    const payload = topArticles.slice(0, 5).map((t) => {
      const src = articles.find((a) => a.slug === t.slug);
      return {
        title: src?.title || t.slug,
        angle: src?.generationMeta?.angle || "",
        categoryId: t.categoryId,
        pv: t[Object.keys(t).find((k) => k.startsWith("pv"))] || 0,
      };
    });
    const res = await client.messages.create({
      model: "claude-sonnet-4-6",
      max_tokens: 800,
      messages: [{
        role: "user",
        content: `次の上位記事データから共通の成功パターンを3〜5個のルールで抽出してください。JSON配列のみで返答。\n${JSON.stringify(payload, null, 2)}`,
      }],
    });
    const text = res.content?.[0]?.text || "";

    // Claude応答のJSONブロック（配列またはオブジェクト）を抽出
    const bracketMatch = text.match(/\[[\s\S]*\]/);
    const braceMatch = text.match(/\{[\s\S]*\}/);
    const jsonText = bracketMatch?.[0] || braceMatch?.[0];
    if (!jsonText) return [];

    const parsed = JSON.parse(jsonText);

    // パターンA: { patterns: [{text: "..."}] } 形式
    if (parsed && typeof parsed === "object" && !Array.isArray(parsed) && Array.isArray(parsed.patterns)) {
      return parsed.patterns
        .map((p) => (typeof p === "string" ? p : p?.text || p?.description || JSON.stringify(p)))
        .filter((p) => typeof p === "string" && p.trim().length > 0)
        .slice(0, 5);
    }

    // パターンB: JSON.parse後が配列
    return Array.isArray(parsed)
      ? parsed
          .map((p) => (typeof p === "string" ? p : JSON.stringify(p)))
          .filter((p) => typeof p === "string" && p.trim().length > 0)
          .slice(0, 5)
      : [];
  } catch (err) {
    console.warn(`[article-analyst] effectivePatterns生成スキップ: ${err.message}`);
    return [];
  }
}

// ─── CLI ─────────────────────────────────────────────

function parseArgs() {
  const args = process.argv.slice(2);
  const opts = { dryRun: false, days: 28 };
  for (let i = 0; i < args.length; i++) {
    switch (args[i]) {
      case "--dry-run": opts.dryRun = true; break;
      case "--days":    opts.days = parseInt(args[++i], 10) || 28; break;
    }
  }
  return opts;
}

// ─── GA4 から記事別PV取得 ────────────────────────────

async function getArticlePVFromGA4(days) {
  const propertyId = process.env.GA4_PROPERTY_ID;
  if (!propertyId) {
    console.warn("[article-analyst] GA4_PROPERTY_ID 未設定。GA4データなしで続行します。");
    return null;
  }

  try {
    const google = await loadGoogle();
    const credentials = JSON.parse(
      process.env.INDEXING_CREDENTIALS || process.env.GOOGLE_CREDENTIALS || "{}"
    );
    const auth = new google.auth.GoogleAuth({
      credentials,
      scopes: ["https://www.googleapis.com/auth/analytics.readonly"],
    });
    const analyticsData = google.analyticsdata({ version: "v1beta", auth });

    const today = new Date();
    const startDate = new Date(today.getTime() - days * 24 * 60 * 60 * 1000);
    const formatDate = (d) => jstDateString(d);

    // 記事ページ別 PV + セッション
    const res = await withTimeout(analyticsData.properties.runReport({
      property: `properties/${propertyId}`,
      requestBody: {
        dateRanges: [{ startDate: formatDate(startDate), endDate: formatDate(today) }],
        dimensions: [{ name: "pagePath" }],
        metrics: [
          { name: "screenPageViews" },
          { name: "sessions" },
        ],
        dimensionFilter: {
          filter: {
            fieldName: "pagePath",
            stringFilter: { matchType: "BEGINS_WITH", value: "/articles/" },
          },
        },
        orderBys: [{ metric: { metricName: "screenPageViews" }, desc: true }],
        limit: 50,
      },
    }), 30_000, "GA4 runReport(PV)");

    // カテゴリ別の検索流入（organic検索のみ）
    const searchRes = await withTimeout(analyticsData.properties.runReport({
      property: `properties/${propertyId}`,
      requestBody: {
        dateRanges: [{ startDate: formatDate(startDate), endDate: formatDate(today) }],
        dimensions: [{ name: "pagePath" }],
        metrics: [{ name: "sessions" }],
        dimensionFilter: {
          andGroup: {
            expressions: [
              {
                filter: {
                  fieldName: "pagePath",
                  stringFilter: { matchType: "BEGINS_WITH", value: "/articles/" },
                },
              },
              {
                filter: {
                  fieldName: "sessionDefaultChannelGroup",
                  stringFilter: { matchType: "EXACT", value: "Organic Search" },
                },
              },
            ],
          },
        },
        orderBys: [{ metric: { metricName: "sessions" }, desc: true }],
        limit: 50,
      },
    }), 30_000, "GA4 runReport(検索流入)");

    const rows = res.data.rows || [];
    const articlePV = rows.map((r) => ({
      slug: r.dimensionValues[0].value.replace("/articles/", "").replace(/\/$/, ""),
      pageViews: parseInt(r.metricValues[0].value),
      sessions: parseInt(r.metricValues[1].value),
    }));

    const searchRows = searchRes.data.rows || [];
    const searchPV = searchRows.map((r) => ({
      slug: r.dimensionValues[0].value.replace("/articles/", "").replace(/\/$/, ""),
      sessions: parseInt(r.metricValues[0].value),
    }));

    return { articlePV, searchPV };
  } catch (err) {
    console.warn(`[article-analyst] GA4取得エラー（スキップ）: ${err.message}`);
    return null;
  }
}

// ─── 分析メイン ──────────────────────────────────────

async function analyze(articles, ga4Data, clicks, days) {
  const now = new Date();

  // 記事別PVマップ
  const pvMap = {};
  if (ga4Data?.articlePV) {
    for (const a of ga4Data.articlePV) {
      pvMap[a.slug] = { pv: a.pageViews, sessions: a.sessions };
    }
  }

  // 記事別クリックマップ
  const clickMap = {};
  for (const c of clicks) {
    const slug = (c.path || "").replace("/articles/", "").replace(/\/$/, "");
    if (slug) clickMap[slug] = (clickMap[slug] || 0) + 1;
  }

  // 既存記事のパフォーマンス
  const topArticles = articles
    .filter((a) => a.status === "published")
    .map((a) => {
      const pv = pvMap[a.slug]?.pv || 0;
      const cl = clickMap[a.slug] || 0;
      return {
        slug: a.slug,
        categoryId: a.categoryId,
        [`pv${days}d`]: pv,
        [`clicks${days}d`]: cl,
        ctr: pv > 0 ? Number(((cl / pv) * 100).toFixed(1)) : 0,
      };
    })
    .sort((a, b) => b[`pv${days}d`] - a[`pv${days}d`])
    .slice(0, 20);

  // カテゴリ別トレンド
  const categoryPV = {};
  for (const a of topArticles) {
    if (!categoryPV[a.categoryId]) categoryPV[a.categoryId] = { pv: 0, clicks: 0 };
    categoryPV[a.categoryId].pv += a[`pv${days}d`];
    categoryPV[a.categoryId].clicks += a[`clicks${days}d`];
  }

  // 検索流入によるカテゴリトレンド
  const searchCategoryPV = {};
  if (ga4Data?.searchPV) {
    for (const s of ga4Data.searchPV) {
      const article = articles.find((a) => a.slug === s.slug);
      if (article) {
        const cat = article.categoryId;
        searchCategoryPV[cat] = (searchCategoryPV[cat] || 0) + s.sessions;
      }
    }
  }

  const categoryTrends = Object.entries(categoryPV)
    .map(([categoryId, data]) => ({
      categoryId,
      [`pv${days}d`]: data.pv,
      [`clicks${days}d`]: data.clicks,
      searchSessions: searchCategoryPV[categoryId] || 0,
      trend: data.pv > 10 ? "active" : "low",
    }))
    .sort((a, b) => b[`pv${days}d`] - a[`pv${days}d`]);

  // 高パフォーマンス記事のパターン抽出
  const effectivePatterns = [];
  const highPerf = topArticles.filter((a) => a.ctr >= 2.0);
  if (highPerf.length > 0) {
    effectivePatterns.push(
      `CTR >= 2.0% の記事: ${highPerf.map((a) => a.slug).join(", ")}`
    );
  }
  const llmPatterns = await generateEffectivePatterns(topArticles, articles);
  effectivePatterns.push(...llmPatterns);

  const suggestions = [];
  // 季節マップを読んで来月の推奨カテゴリを提案
  const seasonMap = readJson("article-season-map.json");
  if (seasonMap) {
    const nextMonth = String(((now.getMonth() + 1) % 12) + 1);
    const nextCats = seasonMap[nextMonth] || [];
    if (nextCats.length > 0) {
      suggestions.push(`来月の季節カテゴリ: ${nextCats.join(", ")} — 準備推奨`);
    }
  }

  return {
    updatedAt: jstIsoString(now),
    period: `${days}d`,
    topArticles,
    categoryTrends,
    effectivePatterns,
    suggestions,
  };
}

// ─── メイン ──────────────────────────────────────────

async function main() {
  const opts = parseArgs();

  const ks = checkArticleKillSwitch();
  if (ks.killed) {
    console.error(`[article-analyst] ${ks.reason}`);
    process.exit(1);
  }

  console.log(`[article-analyst] 分析開始 (過去${opts.days}日)`);

  const articles = readJson("articles.json") || [];
  const allClicks = readJson("affiliate-clicks.json") || [];
  const startDate = jstIsoString(new Date(Date.now() - opts.days * 24 * 60 * 60 * 1000));
  const clicks = allClicks.filter((c) => c.timestamp >= startDate);

  const ga4Data = await getArticlePVFromGA4(opts.days);

  console.log(`[article-analyst] 記事数: ${articles.length}, クリック: ${clicks.length}`);
  if (ga4Data?.articlePV) {
    console.log(`[article-analyst] GA4記事PVデータ: ${ga4Data.articlePV.length}件`);
  }

  const feedback = await analyze(articles, ga4Data, clicks, opts.days);

  console.log("\n[article-analyst] フィードバックサマリ:");
  console.log(`  Top記事: ${feedback.topArticles.slice(0, 5).map((a) => a.slug).join(", ") || "なし"}`);
  console.log(`  カテゴリトレンド: ${feedback.categoryTrends.length}件`);
  console.log(`  有効パターン: ${feedback.effectivePatterns.length}件`);
  console.log(`  提案: ${feedback.suggestions.length}件`);

  if (opts.dryRun) {
    console.log("\n[DRY RUN] article-analyst-feedback.json の書き込みをスキップ");
    console.log(JSON.stringify(feedback, null, 2));
  } else {
    writeJson("article-analyst-feedback.json", feedback);
    console.log("\n[article-analyst] article-analyst-feedback.json を更新しました");
  }
}

main().catch((err) => {
  console.error("[article-analyst] エラー:", err.message);
  process.exit(1);
});
