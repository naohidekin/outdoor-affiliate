#!/usr/bin/env node

/**
 * Viral Scout Agent — バイラル投稿の発見・分析・引用投稿/リプライ生成
 *
 * X API v2 で4軸（AI, camp, parenting, doctor）のバイラル投稿を検索し、
 * Claude API でパターン分析、ギア男のペルソナで引用投稿/リプライを生成する。
 *
 * 必要な環境変数:
 *   TWITTER_BEARER_TOKEN — X API v2 Bearer Token
 *   ANTHROPIC_API_KEY    — Claude API キー
 *
 * 使い方:
 *   node scripts/viral-scout-agent.js                  # フル実行
 *   node scripts/viral-scout-agent.js --dry-run        # 保存なし
 *   node scripts/viral-scout-agent.js --axis ai        # 特定軸のみ
 *   node scripts/viral-scout-agent.js --count=50       # 目標件数
 *   node scripts/viral-scout-agent.js --min-score=50   # 最低エンゲージメントスコア
 */

import { TwitterApi } from "twitter-api-v2";
import fs from "fs";
import path from "path";
import { fileURLToPath } from "url";
import {
  loadEnv,
  readJson,
  writeJson,
  checkKillSwitch,
  ipv4Fetch,
} from "../src/lib/x-agent-utils.mjs";
import { checkXPostContent } from "../src/lib/x-content-checks.mjs";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const DATA_DIR = path.join(__dirname, "..", "data");

loadEnv();

// === CLI オプション ===

function parseArgs() {
  const args = process.argv.slice(2);
  const opts = { axis: null, dryRun: false, count: 50, minScore: 50 };
  for (let i = 0; i < args.length; i++) {
    const arg = args[i];
    const eqIdx = arg.indexOf("=");
    const key = eqIdx !== -1 ? arg.slice(0, eqIdx) : arg;
    const val = eqIdx !== -1 ? arg.slice(eqIdx + 1) : args[i + 1];
    switch (key) {
      case "--axis":      opts.axis = val; if (eqIdx === -1) i++; break;
      case "--dry-run":   opts.dryRun = true; break;
      case "--count":     opts.count = parseInt(val, 10) || 50; if (eqIdx === -1) i++; break;
      case "--min-score": opts.minScore = parseInt(val, 10) || 50; if (eqIdx === -1) i++; break;
    }
  }
  if (opts.axis && !["camp", "ai", "parenting", "doctor"].includes(opts.axis)) {
    console.error(`未知の軸: ${opts.axis}。有効: camp, ai, parenting, doctor`);
    process.exit(1);
  }
  return opts;
}

// === 検索クエリ定義（4軸、エンゲージメントフィルタ付き）===

const AXIS_QUERIES = {
  ai: [
    "(Claude Code OR Claude) -is:retweet lang:ja",
    "(AI 開発 OR AIエージェント OR 生成AI) -is:retweet lang:ja",
    "(ChatGPT OR Copilot OR LLM) -is:retweet lang:ja",
    "(プログラミング AI OR 非エンジニア AI) -is:retweet lang:ja",
    "(個人開発 OR サイト運営 AI) -is:retweet lang:ja",
    "(Claude API OR AIコーディング OR Cursor) -is:retweet lang:ja",
    "(AI自動化 OR AI副業 OR AIツール) -is:retweet lang:ja",
  ],
  camp: [
    "(キャンプ OR アウトドア OR 焚き火) -is:retweet lang:ja",
    "(テント OR シュラフ OR 寝袋) -is:retweet lang:ja",
    "(キャンプギア OR キャンプ道具) -is:retweet lang:ja",
    "(ソロキャンプ OR ファミリーキャンプ) -is:retweet lang:ja",
    "(キャンプ飯 OR メスティン OR ホットサンド) -is:retweet lang:ja",
  ],
  parenting: [
    "(子連れ キャンプ OR 家族 キャンプ) -is:retweet lang:ja",
    "(子育て アウトドア OR 子供 自然体験) -is:retweet lang:ja",
    "(パパキャンプ OR ママキャンプ) -is:retweet lang:ja",
  ],
  doctor: [
    "(開業医 OR クリニック経営) -is:retweet lang:ja",
    "(医師 日常 OR 医師 趣味) -is:retweet lang:ja",
    "(勤務医 OR 医者 副業 OR ドクター) -is:retweet lang:ja",
    "(医師 ワークライフバランス OR 医者 休日) -is:retweet lang:ja",
  ],
};

// 各軸の目標件数（合計50件）
const AXIS_TARGETS = { ai: 20, camp: 13, parenting: 10, doctor: 7 };

// === エンゲージメントスコア ===

function engagementScore(m) {
  return (
    (m.like_count || m.likes || 0) +
    (m.retweet_count || m.retweets || 0) * 3 +
    (m.reply_count || m.replies || 0) * 2 +
    (m.quote_count || m.quotes || 0) * 2
  );
}

// === X API クライアント生成 ===

function getXClient() {
  // Bearer Token があればそれを使う（search は App-only auth 推奨）
  const bearerToken = process.env.TWITTER_BEARER_TOKEN;
  if (bearerToken) {
    return new TwitterApi(bearerToken);
  }
  // なければ OAuth 1.0a User Context（post-to-x.js と同じパターン）
  const { X_API_KEY, X_API_SECRET, X_ACCESS_TOKEN, X_ACCESS_SECRET } = process.env;
  if (!X_API_KEY || !X_API_SECRET || !X_ACCESS_TOKEN || !X_ACCESS_SECRET) {
    console.error("TWITTER_BEARER_TOKEN または X_API_KEY/X_API_SECRET/X_ACCESS_TOKEN/X_ACCESS_SECRET が必要です");
    process.exit(1);
  }
  return new TwitterApi({
    appKey: X_API_KEY,
    appSecret: X_API_SECRET,
    accessToken: X_ACCESS_TOKEN,
    accessSecret: X_ACCESS_SECRET,
  });
}

// === X API v2 検索 ===

async function searchRecentTweets(client, query, maxResults = 100) {
  const response = await client.v2.search(query, {
    max_results: Math.min(maxResults, 100),
    "tweet.fields": ["public_metrics", "created_at", "author_id", "entities"],
    expansions: ["author_id"],
    "user.fields": ["username", "name", "public_metrics"],
    sort_order: "relevancy",
  });

  const tweets = response.data?.data || [];
  const users = {};
  for (const u of response.data?.includes?.users || []) {
    users[u.id] = { username: u.username, name: u.name, followers: u.public_metrics?.followers_count || 0 };
  }

  return tweets.map((t) => {
    const m = t.public_metrics || {};
    return {
      id: t.id,
      text: t.text,
      authorId: t.author_id,
      authorUsername: users[t.author_id]?.username || "unknown",
      authorName: users[t.author_id]?.name || "",
      authorFollowers: users[t.author_id]?.followers || 0,
      createdAt: t.created_at,
      metrics: {
        likes: m.like_count || 0,
        retweets: m.retweet_count || 0,
        replies: m.reply_count || 0,
        quotes: m.quote_count || 0,
        bookmarks: m.bookmark_count || 0,
        engagementScore: engagementScore(m),
      },
    };
  });
}

// === Phase 1: Scout ===

async function scoutViralPosts(client, opts) {
  const targetAxes = opts.axis ? [opts.axis] : Object.keys(AXIS_QUERIES);
  const allPosts = [];
  const seenIds = new Set();

  for (const axis of targetAxes) {
    const queries = AXIS_QUERIES[axis];
    const target = AXIS_TARGETS[axis] || 10;
    const axisPosts = [];

    console.log(`\n[${axis}] 検索開始（目標: ${target}件）...`);

    for (const query of queries) {
      try {
        const tweets = await searchRecentTweets(client, query, 100);
        let added = 0;

        for (const tweet of tweets) {
          if (seenIds.has(tweet.id)) continue;
          if (tweet.metrics.engagementScore < opts.minScore) continue;
          // 自分のアカウントを除外
          if (tweet.authorUsername === "camp_gear_lab") continue;

          seenIds.add(tweet.id);
          axisPosts.push({ ...tweet, axis });
          added++;
        }

        console.log(`  「${query.slice(0, 50)}...」→ ${tweets.length}件取得, ${added}件採用`);

        // レート制限対策（1.5秒間隔）
        await new Promise((r) => setTimeout(r, 1500));
      } catch (err) {
        if (err.code === 429 || err.message?.includes("429")) {
          console.warn(`  [${axis}] レート制限 — 15秒待機`);
          await new Promise((r) => setTimeout(r, 15000));
          continue;
        }
        if (err.code === 402 || err.message?.includes("402")) {
          console.warn(`  [${axis}] API上限到達 (402) — この軸の残りクエリをスキップ`);
          break;
        }
        console.warn(`  [${axis}] 検索エラー: ${err.message}`);
      }
    }

    // エンゲージメント順にソートして目標件数まで絞る
    axisPosts.sort((a, b) => b.metrics.engagementScore - a.metrics.engagementScore);
    const selected = axisPosts.slice(0, target);
    allPosts.push(...selected);

    console.log(`  [${axis}] 結果: ${axisPosts.length}件中 ${selected.length}件を採用（top engagement: ${selected[0]?.metrics.engagementScore || 0}）`);
  }

  // 全体をエンゲージメント順に再ソート
  allPosts.sort((a, b) => b.metrics.engagementScore - a.metrics.engagementScore);
  return allPosts.slice(0, opts.count);
}

// === Phase 2: Analyze ===

async function analyzeViralPatterns(client, posts) {
  console.log(`\n[分析] ${posts.length}件のバイラルポストを分析中...`);
  const analyzed = [];
  const batchSize = 10;

  for (let i = 0; i < posts.length; i += batchSize) {
    const batch = posts.slice(i, i + batchSize);
    const batchNum = Math.floor(i / batchSize) + 1;
    const totalBatches = Math.ceil(posts.length / batchSize);

    console.log(`  バッチ ${batchNum}/${totalBatches} (${batch.length}件)...`);

    const tweetsText = batch
      .map(
        (p, idx) =>
          `[${idx + 1}] @${p.authorUsername} (フォロワー${p.authorFollowers})\n軸: ${p.axis}\nいいね${p.metrics.likes} RT${p.metrics.retweets} リプ${p.metrics.replies} 引用${p.metrics.quotes}\n---\n${p.text}\n---`
      )
      .join("\n\n");

    try {
      const response = await client.messages.create({
        model: "claude-sonnet-4-20250514",
        max_tokens: 4000,
        messages: [
          {
            role: "user",
            content: `あなたはX（旧Twitter）のバイラルコンテンツアナリストです。以下の高エンゲージメント投稿のバズった要因を分析してください。

## 投稿
${tweetsText}

## 分析（JSON配列で出力）
各投稿について:
[
  {
    "index": 1,
    "hook": "書き出しテクニック (conclusion_first/number_hook/failure_open/question/reveal/self_disclosure/contrast/poll/hot_take/other)",
    "emotionalTrigger": "主な感情トリガー (curiosity/empathy/FOMO/humor/nostalgia/controversy/utility/identity/surprise)",
    "format": "投稿フォーマット (list/comparison/story/poll/hot_take/thread_bait/one_liner/experience_share/data_point)",
    "topic": "具体的なトピック（10文字以内）",
    "timing": "なぜこのタイミングで伸びたか（20文字以内）",
    "shareability": "RT/引用される理由 (utility/humor/identity/debate/emotional/FOMO)",
    "keyTechniques": ["使われている具体的テクニック（2-3個）"],
    "adaptability": "ギア男（37歳医師キャンパー、AI開発者）のペルソナとの親和性 (high/medium/low)"
  }
]`,
          },
        ],
      });

      const text = response.content[0].text;
      const jsonMatch = text.match(/\[[\s\S]*\]/);
      if (jsonMatch) {
        const analyses = JSON.parse(jsonMatch[0]);
        for (let j = 0; j < batch.length && j < analyses.length; j++) {
          analyzed.push({
            ...batch[j],
            analysis: analyses[j],
          });
        }
      } else {
        // JSON抽出失敗 → 分析なしで追加
        for (const p of batch) {
          analyzed.push({ ...p, analysis: null });
        }
      }
    } catch (err) {
      console.warn(`  分析エラー (バッチ${batchNum}): ${err.message}`);
      for (const p of batch) {
        analyzed.push({ ...p, analysis: null });
      }
    }

    // API間隔
    if (i + batchSize < posts.length) {
      await new Promise((r) => setTimeout(r, 1000));
    }
  }

  return analyzed;
}

// === Phase 2.5: 集計分析 ===

function aggregateAnalysis(posts) {
  const analyzed = posts.filter((p) => p.analysis);
  if (analyzed.length === 0) return null;

  const count = (arr, key) => {
    const freq = {};
    for (const item of arr) {
      const val = item.analysis[key];
      if (val) freq[val] = (freq[val] || 0) + 1;
    }
    return Object.entries(freq)
      .sort((a, b) => b[1] - a[1])
      .map(([k, v]) => ({ pattern: k, count: v, pct: Math.round((v / arr.length) * 100) }));
  };

  // 軸ごとのエンゲージメント平均
  const byAxis = {};
  for (const p of analyzed) {
    if (!byAxis[p.axis]) byAxis[p.axis] = { count: 0, totalScore: 0, posts: [] };
    byAxis[p.axis].count++;
    byAxis[p.axis].totalScore += p.metrics.engagementScore;
    byAxis[p.axis].posts.push(p);
  }

  const axisStats = {};
  for (const [axis, data] of Object.entries(byAxis)) {
    axisStats[axis] = {
      count: data.count,
      avgEngagement: Math.round(data.totalScore / data.count),
      topHooks: count(data.posts, "hook").slice(0, 3),
      topTriggers: count(data.posts, "emotionalTrigger").slice(0, 3),
      topFormats: count(data.posts, "format").slice(0, 3),
    };
  }

  // テクニックの頻度集計
  const techFreq = {};
  for (const p of analyzed) {
    for (const tech of p.analysis.keyTechniques || []) {
      techFreq[tech] = (techFreq[tech] || 0) + 1;
    }
  }
  const topTechniques = Object.entries(techFreq)
    .sort((a, b) => b[1] - a[1])
    .slice(0, 10)
    .map(([k, v]) => ({ technique: k, count: v }));

  return {
    totalAnalyzed: analyzed.length,
    topHooks: count(analyzed, "hook").slice(0, 5),
    topEmotionalTriggers: count(analyzed, "emotionalTrigger").slice(0, 5),
    topFormats: count(analyzed, "format").slice(0, 5),
    topShareability: count(analyzed, "shareability").slice(0, 5),
    topTechniques,
    byAxis: axisStats,
    highAdaptability: analyzed.filter((p) => p.analysis.adaptability === "high").length,
  };
}

// === Phase 3: Generate ===

async function generateContent(client, posts) {
  console.log(`\n[生成] ${posts.length}件の引用投稿・リプライを生成中...`);
  const results = [];
  const batchSize = 5;

  // account-config.json からペルソナ情報を取得
  const config = readJson("account-config.json") || {};
  const persona = config.persona || {};

  const personaPreamble = `あなたは「ギア男」です。
- ${persona.age || 37}歳、${persona.location || "長野県"}在住の${persona.occupation || "医師"}
- キャンプ歴${persona.experience || "10年"}、家族キャンプ中心
- 性格: 買う前に徹底比較するスペック厨だが押しつけがましくない
- AIでサイト作りにハマっている非エンジニア医師
- 文体: 友人に話しかけるような温かさ。一人称「僕」
- トーン別:
  - camp軸: ですます調、体験ベースの具体的な話
  - ai軸: やや砕けた開発日記調
  - parenting軸: ほっこり〜自虐
  - doctor軸: 「本職柄〜」控えめ匂わせ（「小児科医」とは明言しない）`;

  for (let i = 0; i < posts.length; i += batchSize) {
    const batch = posts.slice(i, i + batchSize);
    const batchNum = Math.floor(i / batchSize) + 1;
    const totalBatches = Math.ceil(posts.length / batchSize);

    console.log(`  バッチ ${batchNum}/${totalBatches} (${batch.length}件)...`);

    const tweetsText = batch
      .map(
        (p, idx) =>
          `[${idx + 1}] @${p.authorUsername} (軸: ${p.axis})\n投稿: ${p.text}\nいいね${p.metrics.likes} RT${p.metrics.retweets}\nバズ要因: ${p.analysis?.hook || "不明"} / ${p.analysis?.emotionalTrigger || "不明"}`
      )
      .join("\n\n");

    try {
      const response = await client.messages.create({
        model: "claude-sonnet-4-20250514",
        max_tokens: 6000,
        messages: [
          {
            role: "user",
            content: `${personaPreamble}

## タスク
以下のバイラル投稿に対して、(A) バズる引用投稿 と (B) バズるリプライ を作ってください。

## ルール
- 引用投稿: 200文字以内。ギア男の独自視点・体験・知見を追加。「すごい！」等の空っぽな賞賛は禁止
- リプライ: 200文字以内。会話への貢献（体験談, データ, 質問, 別視点）。宣伝・リンク貼りなし
- 軸クロスの視点を活かす（例: AI投稿にキャンプ好き医師として反応 → 印象に残る）
- 絵文字は0〜1個。顔文字は使わない
- 以下のNGワードは使用禁止: 最高, 最強, 絶対, 神, 革命, 奇跡, ヤバい
- 医療系の断言（治る, 効く, 改善する等）は禁止

## 投稿
${tweetsText}

## 出力（JSON配列）
[
  {
    "index": 1,
    "quoteTweet": "引用投稿テキスト",
    "quoteAxis": "この引用投稿の軸 (camp/ai/parenting/doctor)",
    "quoteRationale": "なぜこのアプローチか（20文字以内）",
    "reply": "リプライテキスト",
    "replyAxis": "このリプライの軸",
    "replyRationale": "なぜこのリプライか（20文字以内）"
  }
]`,
          },
        ],
      });

      const text = response.content[0].text;
      const jsonMatch = text.match(/\[[\s\S]*\]/);
      if (jsonMatch) {
        const generated = JSON.parse(jsonMatch[0]);
        for (let j = 0; j < batch.length && j < generated.length; j++) {
          const g = generated[j];
          const post = batch[j];

          // NG検証
          const quoteCheck = checkXPostContent(g.quoteTweet || "");
          const replyCheck = checkXPostContent(g.reply || "");

          results.push({
            ...post,
            generatedContent: {
              quoteTweet: {
                text: g.quoteTweet || "",
                axis: g.quoteAxis || post.axis,
                rationale: g.quoteRationale || "",
                validationErrors: [...quoteCheck.errors, ...quoteCheck.warnings].join(" / ") || undefined,
                status: quoteCheck.ok ? "draft" : "needs_review",
              },
              reply: {
                text: g.reply || "",
                axis: g.replyAxis || post.axis,
                rationale: g.replyRationale || "",
                validationErrors: [...replyCheck.errors, ...replyCheck.warnings].join(" / ") || undefined,
                status: replyCheck.ok ? "draft" : "needs_review",
              },
            },
          });
        }
      } else {
        for (const p of batch) {
          results.push({ ...p, generatedContent: null });
        }
      }
    } catch (err) {
      console.warn(`  生成エラー (バッチ${batchNum}): ${err.message}`);
      for (const p of batch) {
        results.push({ ...p, generatedContent: null });
      }
    }

    if (i + batchSize < posts.length) {
      await new Promise((r) => setTimeout(r, 1000));
    }
  }

  return results;
}

// === buzz-first-lines.json 更新 ===

function updateBuzzFirstLines(posts) {
  const buzzPath = path.join(DATA_DIR, "buzz-first-lines.json");
  let buzzData = [];
  if (fs.existsSync(buzzPath)) {
    buzzData = JSON.parse(fs.readFileSync(buzzPath, "utf-8"));
    if (!Array.isArray(buzzData)) buzzData = buzzData.lines || buzzData.entries || [];
  }

  // トップ20のバイラル書き出しを追加
  const topPosts = posts
    .filter((p) => p.analysis)
    .sort((a, b) => b.metrics.engagementScore - a.metrics.engagementScore)
    .slice(0, 20);

  let added = 0;
  for (const p of topPosts) {
    const firstLine = p.text.split("\n").filter((l) => l.trim())[0] || "";
    if (!firstLine || firstLine.length < 5) continue;

    // 重複チェック
    const isDupe = buzzData.some((b) => b.text === firstLine);
    if (isDupe) continue;

    buzzData.push({
      text: firstLine,
      source: "viral_scout",
      axis: p.axis,
      postType: null,
      pattern: p.analysis?.hook || "other",
      likes: p.metrics.likes,
      retweets: p.metrics.retweets,
      bookmarks: p.metrics.bookmarks,
      replies: p.metrics.replies,
      originalAuthor: `@${p.authorUsername}`,
      collectedAt: new Date().toISOString().slice(0, 10),
    });
    added++;
  }

  return { buzzData, added };
}

// === メインレポート出力 ===

function printReport(posts, aggregate) {
  console.log("\n" + "=".repeat(60));
  console.log("  バイラルスカウト結果レポート");
  console.log("=".repeat(60));

  console.log(`\n総収集数: ${posts.length}件`);

  // 軸別
  const byAxis = {};
  for (const p of posts) {
    if (!byAxis[p.axis]) byAxis[p.axis] = [];
    byAxis[p.axis].push(p);
  }
  for (const [axis, axisPosts] of Object.entries(byAxis)) {
    const avgScore = Math.round(axisPosts.reduce((s, p) => s + p.metrics.engagementScore, 0) / axisPosts.length);
    console.log(`  [${axis}] ${axisPosts.length}件 / 平均エンゲージメント: ${avgScore}`);
  }

  if (aggregate) {
    console.log("\n--- 全体パターン分析 ---");
    console.log(`トップフック: ${aggregate.topHooks.map((h) => `${h.pattern}(${h.count})`).join(", ")}`);
    console.log(`トップ感情トリガー: ${aggregate.topEmotionalTriggers.map((t) => `${t.pattern}(${t.count})`).join(", ")}`);
    console.log(`トップフォーマット: ${aggregate.topFormats.map((f) => `${f.pattern}(${f.count})`).join(", ")}`);
    console.log(`ギア男適応性「高」: ${aggregate.highAdaptability}件`);

    if (aggregate.topTechniques.length > 0) {
      console.log(`\n--- よく使われるテクニック ---`);
      for (const t of aggregate.topTechniques.slice(0, 5)) {
        console.log(`  ${t.technique} (${t.count}回)`);
      }
    }
  }

  // 生成コンテンツのサマリー
  const withContent = posts.filter((p) => p.generatedContent);
  const quoteOk = withContent.filter((p) => p.generatedContent?.quoteTweet?.status === "draft").length;
  const replyOk = withContent.filter((p) => p.generatedContent?.reply?.status === "draft").length;
  console.log(`\n--- 生成コンテンツ ---`);
  console.log(`引用投稿: ${quoteOk}件 OK / ${withContent.length - quoteOk}件 要レビュー`);
  console.log(`リプライ: ${replyOk}件 OK / ${withContent.length - replyOk}件 要レビュー`);

  // トップ5の投稿を表示
  console.log("\n--- トップ5バイラル投稿 ---");
  for (const p of posts.slice(0, 5)) {
    console.log(`\n@${p.authorUsername} [${p.axis}] score:${p.metrics.engagementScore} ♥${p.metrics.likes} RT${p.metrics.retweets}`);
    console.log(`  ${p.text.slice(0, 100)}${p.text.length > 100 ? "..." : ""}`);
    if (p.generatedContent?.quoteTweet) {
      console.log(`  → 引用: ${p.generatedContent.quoteTweet.text.slice(0, 80)}...`);
    }
    if (p.generatedContent?.reply) {
      console.log(`  → リプ: ${p.generatedContent.reply.text.slice(0, 80)}...`);
    }
  }
}

// === メイン ===

async function main() {
  const opts = parseArgs();

  // Kill Switch チェック
  const ks = checkKillSwitch();
  if (ks.killed) {
    console.error(`[viral-scout] KILL SWITCH 有効: ${ks.reason}`);
    process.exit(1);
  }

  const anthropicKey = process.env.ANTHROPIC_API_KEY;
  if (!anthropicKey) {
    console.error("[viral-scout] ANTHROPIC_API_KEY が設定されていません");
    process.exit(1);
  }

  const xClient = getXClient();

  const Anthropic = (await import("@anthropic-ai/sdk")).default;
  const claude = new Anthropic({ apiKey: anthropicKey, fetch: ipv4Fetch, maxRetries: 3 });

  console.log("=== Viral Scout Agent ===");
  console.log(`目標: ${opts.count}件 / 最低スコア: ${opts.minScore} / 軸: ${opts.axis || "全軸"}`);

  // Phase 1: Scout
  console.log("\n[Phase 1] バイラルポスト検索...");
  const scoutedPosts = await scoutViralPosts(xClient, opts);
  console.log(`\n[Phase 1 完了] ${scoutedPosts.length}件のバイラルポストを収集`);

  if (scoutedPosts.length === 0) {
    console.log("対象となるバイラルポストが見つかりませんでした。min-score を下げてリトライしてください。");
    return;
  }

  // Phase 2: Analyze
  console.log("\n[Phase 2] パターン分析...");
  const analyzedPosts = await analyzeViralPatterns(claude, scoutedPosts);
  const aggregate = aggregateAnalysis(analyzedPosts);

  // Phase 3: Generate
  console.log("\n[Phase 3] 引用投稿・リプライ生成...");
  const finalPosts = await generateContent(claude, analyzedPosts);

  // レポート出力
  printReport(finalPosts, aggregate);

  if (opts.dryRun) {
    console.log("\n[DRY RUN] ファイル保存をスキップ");
    return;
  }

  // 保存
  const today = new Date().toISOString().slice(0, 10);
  const output = {
    version: 1,
    scoutedAt: new Date().toISOString(),
    config: {
      minEngagementScore: opts.minScore,
      targetCount: opts.count,
      actualCount: finalPosts.length,
      axes: opts.axis ? [opts.axis] : Object.keys(AXIS_QUERIES),
    },
    aggregateAnalysis: aggregate,
    viralPosts: finalPosts.map((p) => ({
      tweetId: p.id,
      authorUsername: p.authorUsername,
      authorName: p.authorName,
      authorFollowers: p.authorFollowers,
      axis: p.axis,
      text: p.text,
      createdAt: p.createdAt,
      metrics: p.metrics,
      analysis: p.analysis,
      generatedContent: p.generatedContent,
    })),
  };

  writeJson("viral-scout-results.json", output);
  console.log(`\n保存完了: data/viral-scout-results.json`);

  // buzz-first-lines.json 更新
  const { buzzData, added } = updateBuzzFirstLines(finalPosts);
  if (added > 0) {
    const buzzPath = path.join(DATA_DIR, "buzz-first-lines.json");
    fs.writeFileSync(buzzPath, JSON.stringify(buzzData, null, 2) + "\n", "utf-8");
    console.log(`buzz-first-lines.json に ${added}件追加`);
  }

  console.log("\n[完了] Viral Scout Agent 終了");
}

main().catch((err) => {
  console.error("[viral-scout] エラー:", err.message);
  process.exit(1);
});
