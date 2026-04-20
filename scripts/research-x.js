#!/usr/bin/env node

/**
 * X リサーチスクリプト
 * 高エンゲージメント投稿を軸ごとに検索し、パターンを抽出して
 * data/x-research/YYYY-MM-DD.json に保存する。
 *
 * 使い方:
 *   node scripts/research-x.js              # 全軸を検索
 *   node scripts/research-x.js --axis camp  # 特定軸のみ
 *   node scripts/research-x.js --dry-run    # 保存せず出力のみ
 */

import { TwitterApi } from "twitter-api-v2";
import fs from "fs";
import path from "path";
import { fileURLToPath } from "url";
import { loadEnv, readJson, writeJson } from "../src/lib/x-agent-utils.mjs";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const DATA_DIR = path.join(__dirname, "..", "data");

loadEnv();

// === CLI オプション ===

function parseArgs() {
  const args = process.argv.slice(2);
  const opts = { axis: null, dryRun: false };
  for (let i = 0; i < args.length; i++) {
    const arg = args[i];
    const eqIdx = arg.indexOf("=");
    const key = eqIdx !== -1 ? arg.slice(0, eqIdx) : arg;
    const val = eqIdx !== -1 ? arg.slice(eqIdx + 1) : args[i + 1];
    switch (key) {
      case "--axis":    opts.axis = val; if (eqIdx === -1) i++; break;
      case "--dry-run": opts.dryRun = true; break;
    }
  }
  if (opts.axis && !["camp", "ai", "parenting", "doctor"].includes(opts.axis)) {
    console.error(`未知の軸: ${opts.axis}。有効: camp, ai, parenting, doctor`);
    process.exit(1);
  }
  return opts;
}

// === 検索クエリ定義 ===

const AXIS_QUERIES = {
  camp: [
    "lang:ja キャンプ ギア -is:retweet -is:reply",
    "lang:ja テント アウトドア -is:retweet -is:reply",
    "lang:ja ファミリーキャンプ -is:retweet -is:reply",
  ],
  ai: [
    "lang:ja Claude Code -is:retweet -is:reply",
    "lang:ja AI開発 エンジニア -is:retweet -is:reply",
    "lang:ja ChatGPT 活用 -is:retweet -is:reply",
  ],
  parenting: [
    "lang:ja 子育て アウトドア -is:retweet -is:reply",
    "lang:ja パパキャンプ OR ファミキャン -is:retweet -is:reply",
    "lang:ja 子供 外遊び 自然 -is:retweet -is:reply",
  ],
  doctor: [
    "lang:ja 医師 健康 -is:retweet -is:reply",
    "lang:ja 小児科 子育て -is:retweet -is:reply",
    "lang:ja 子供 病気 予防 -is:retweet -is:reply",
  ],
};

// === パターン抽出 ===

function extractPattern(text) {
  const lines = text.split("\n").filter((l) => l.trim());
  const firstLine = lines[0] || "";
  const charCount = text.length;
  const lineCount = lines.length;
  const emojiCount = (text.match(/[\p{Emoji}]/gu) || []).length;
  const hasNumbers = /[0-9０-９]/.test(text);
  const hasQuestion = /[？?]/.test(firstLine);
  const hasExclamation = /[！!]/.test(firstLine);
  const hashtagCount = (text.match(/#\S+/g) || []).length;
  const hasUrl = /https?:\/\//.test(text);
  const hasList = /^[・▸✓\-●◆]|\d+[\.）\)]/m.test(text);
  const hasSelfDisclosure = /僕|私|俺|自分|うち/.test(firstLine);

  // フックパターン分類
  let hookPattern = "other";
  if (hasQuestion) hookPattern = "question";
  else if (/^実は|^じつは|^知らない|^意外に/.test(firstLine)) hookPattern = "reveal";
  else if (/^\d+|^[０-９]/.test(firstLine)) hookPattern = "number_list";
  else if (hasSelfDisclosure) hookPattern = "self_disclosure";
  else if (/失敗|後悔|やらかし/.test(firstLine)) hookPattern = "failure";
  else if (/買った|購入|試した/.test(firstLine)) hookPattern = "review";

  return {
    charCount,
    lineCount,
    emojiCount,
    hasNumbers,
    hasQuestion,
    hasExclamation,
    hashtagCount,
    hasUrl,
    hasList,
    hookPattern,
  };
}

// === Analyst 要約生成 ===

function summarizePatterns(posts) {
  if (posts.length === 0) return null;

  const patterns = posts.map((p) => p.pattern);

  const avgChars = Math.round(patterns.reduce((s, p) => s + p.charCount, 0) / patterns.length);
  const avgLines = Math.round((patterns.reduce((s, p) => s + p.lineCount, 0) / patterns.length) * 10) / 10;
  const avgEmoji = Math.round((patterns.reduce((s, p) => s + p.emojiCount, 0) / patterns.length) * 10) / 10;

  // フックパターンの頻度集計
  const hookFreq = {};
  for (const p of patterns) {
    hookFreq[p.hookPattern] = (hookFreq[p.hookPattern] || 0) + 1;
  }
  const topHooks = Object.entries(hookFreq)
    .sort((a, b) => b[1] - a[1])
    .slice(0, 3)
    .map(([k, v]) => `${k}(${v}件)`);

  const listRate = Math.round((patterns.filter((p) => p.hasList).length / patterns.length) * 100);
  const urlRate = Math.round((patterns.filter((p) => p.hasUrl).length / patterns.length) * 100);
  const hashtagRate = Math.round((patterns.filter((p) => p.hashtagCount > 0).length / patterns.length) * 100);

  return {
    sampleCount: posts.length,
    avgChars,
    avgLines,
    avgEmoji,
    topHooks,
    listRate,
    urlRate,
    hashtagRate,
    insight: buildInsight({ avgChars, avgLines, avgEmoji, topHooks, listRate, urlRate }),
  };
}

function buildInsight({ avgChars, avgLines, avgEmoji, topHooks, listRate, urlRate }) {
  const parts = [];
  parts.push(`平均${avgChars}文字/${avgLines}行`);
  if (avgEmoji >= 1) parts.push(`絵文字${avgEmoji}個/投稿`);
  if (topHooks.length > 0) parts.push(`主要フック: ${topHooks.join(", ")}`);
  if (listRate >= 30) parts.push(`リスト型が${listRate}%`);
  if (urlRate < 20) parts.push("URL少なめ（本文リンクなしが主流）");
  return parts.join(" / ");
}

// === メイン ===

async function runResearch(opts) {
  const bearerToken = process.env.TWITTER_BEARER_TOKEN;
  if (!bearerToken) {
    console.error("TWITTER_BEARER_TOKEN が設定されていません");
    process.exit(1);
  }

  const client = new TwitterApi(bearerToken);
  const today = new Date().toISOString().slice(0, 10);
  const result = { date: today, axes: {} };

  const targetAxes = opts.axis ? [opts.axis] : Object.keys(AXIS_QUERIES);

  for (const axis of targetAxes) {
    const queries = AXIS_QUERIES[axis];
    const axisResult = { posts: [], summary: null };

    console.log(`\n[${axis}] 検索開始...`);

    for (const query of queries) {
      try {
        // 各クエリで最大10件取得（無料枠節約）
        const response = await client.v2.search(query, {
          max_results: 10,
          "tweet.fields": ["public_metrics", "created_at", "author_id", "text"],
          sort_order: "relevancy",
        });

        const tweets = response.data?.data || [];

        for (const tweet of tweets) {
          const metrics = tweet.public_metrics || {};
          const engagementScore =
            (metrics.like_count || 0) * 2 +
            (metrics.retweet_count || 0) * 3 +
            (metrics.reply_count || 0) +
            (metrics.bookmark_count || 0) * 2;

          // 最低エンゲージメント閾値（低エンゲージメントは学習しない）
          if (engagementScore < 5) continue;

          axisResult.posts.push({
            id: tweet.id,
            text: tweet.text,
            metrics: {
              likes: metrics.like_count || 0,
              retweets: metrics.retweet_count || 0,
              replies: metrics.reply_count || 0,
              bookmarks: metrics.bookmark_count || 0,
              engagementScore,
            },
            createdAt: tweet.created_at,
            pattern: extractPattern(tweet.text),
          });
        }

        console.log(`  [${axis}] クエリ「${query.slice(0, 40)}...」→ ${tweets.length}件取得`);

        // レート制限対策
        await new Promise((r) => setTimeout(r, 1500));
      } catch (err) {
        if (err.code === 429) {
          console.warn(`  [${axis}] レート制限 — この軸の検索をスキップ`);
          break;
        }
        console.warn(`  [${axis}] 検索エラー: ${err.message}`);
      }
    }

    // エンゲージメント順にソートして上位20件を保持
    axisResult.posts.sort((a, b) => b.metrics.engagementScore - a.metrics.engagementScore);
    axisResult.posts = axisResult.posts.slice(0, 20);
    axisResult.summary = summarizePatterns(axisResult.posts);

    result.axes[axis] = axisResult;

    if (axisResult.summary) {
      console.log(`  [${axis}] 集計: ${axisResult.summary.insight}`);
    }
  }

  if (opts.dryRun) {
    console.log("\n[DRY RUN] 保存をスキップ。結果のサマリー:");
    for (const [axis, data] of Object.entries(result.axes)) {
      console.log(`  ${axis}: ${data.posts.length}件 / ${data.summary?.insight || "データなし"}`);
    }
    return;
  }

  // 保存
  const researchDir = path.join(DATA_DIR, "x-research");
  if (!fs.existsSync(researchDir)) fs.mkdirSync(researchDir, { recursive: true });

  const outPath = path.join(researchDir, `${today}.json`);
  fs.writeFileSync(outPath, JSON.stringify(result, null, 2) + "\n", "utf-8");
  console.log(`\n保存完了: ${outPath}`);
  console.log(`取得件数: ${Object.entries(result.axes).map(([k, v]) => `${k}(${v.posts.length}件)`).join(", ")}`);
}

const opts = parseArgs();
runResearch(opts).catch((err) => {
  console.error("エラー:", err.message);
  process.exit(1);
});
