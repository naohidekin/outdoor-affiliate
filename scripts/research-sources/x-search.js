#!/usr/bin/env node

/**
 * X (Twitter) リサーチソース
 *
 * X API v2 の Recent Search を使ってキャンプ・アウトドア関連ツイートを収集し、
 * Claude でネタ抽出して x-content-seeds.json に追加する。
 *
 * 必要な環境変数:
 *   TWITTER_BEARER_TOKEN — X API v2 Bearer Token
 *   ANTHROPIC_API_KEY    — Claude API キー
 *
 * 使い方:
 *   node scripts/research-sources/x-search.js
 *   node scripts/research-sources/x-search.js --dry-run
 *   node scripts/research-sources/x-search.js --axis camp
 */

import {
  loadEnv,
  readJson,
  writeJson,
  checkKillSwitch,
  ipv4Fetch,
} from "../../src/lib/x-agent-utils.mjs";

loadEnv();

// ─── 検索クエリ定義 ───────────────────────────────────

const SEARCH_QUERIES = {
  camp: [
    "キャンプギア おすすめ -is:retweet lang:ja",
    "ソロキャンプ 道具 -is:retweet lang:ja",
    "ファミリーキャンプ コツ -is:retweet lang:ja",
    "キャンプ場 穴場 -is:retweet lang:ja",
    "焚き火台 レビュー -is:retweet lang:ja",
  ],
  ai: [
    "Claude Code 個人開発 -is:retweet lang:ja",
    "生成AI 活用 -is:retweet lang:ja",
  ],
  parenting: [
    "子連れキャンプ 持ち物 -is:retweet lang:ja",
    "ファミキャン 初心者 -is:retweet lang:ja",
  ],
  doctor: [
    "キャンプ 応急処置 -is:retweet lang:ja",
    "アウトドア 熱中症 対策 -is:retweet lang:ja",
  ],
};

// ─── X API v2 Recent Search ───────────────────────────

async function searchRecentTweets(bearerToken, query, maxResults = 10) {
  const url = `https://api.twitter.com/2/tweets/search/recent?query=${encodeURIComponent(query)}&max_results=${maxResults}&tweet.fields=public_metrics,created_at`;
  const res = await fetch(url, {
    headers: {
      Authorization: `Bearer ${bearerToken}`,
    },
  });
  if (!res.ok) {
    const body = await res.text().catch(() => "");
    throw new Error(`X API 失敗 (${res.status}): ${body.slice(0, 200)}`);
  }
  const data = await res.json();
  return (data.data || []).map((t) => ({
    text: t.text,
    likes: t.public_metrics?.like_count || 0,
    retweets: t.public_metrics?.retweet_count || 0,
    replies: t.public_metrics?.reply_count || 0,
  }));
}

// ─── メイン ──────────────────────────────────────────

async function main() {
  const args = process.argv.slice(2);
  const dryRun = args.includes("--dry-run");
  const axisArg = args.find((a, i) => args[i - 1] === "--axis");

  const ks = checkKillSwitch();
  if (ks.killed) {
    console.error(`[x-search] KILL SWITCH 有効: ${ks.reason}`);
    process.exit(1);
  }

  const bearerToken = process.env.TWITTER_BEARER_TOKEN;
  if (!bearerToken) {
    console.log("[x-search] TWITTER_BEARER_TOKEN 未設定。スキップ。");
    return;
  }

  const anthropicKey = process.env.ANTHROPIC_API_KEY;
  if (!anthropicKey) {
    console.error("[x-search] ANTHROPIC_API_KEY 未設定");
    process.exit(1);
  }

  const Anthropic = (await import("@anthropic-ai/sdk")).default;
  const client = new Anthropic({ apiKey: anthropicKey, fetch: ipv4Fetch, maxRetries: 3 });

  const seedData = readJson("x-content-seeds.json") || { seeds: [] };
  const axes = axisArg ? [axisArg] : Object.keys(SEARCH_QUERIES);

  let addedCount = 0;

  for (const axis of axes) {
    const queries = SEARCH_QUERIES[axis] || [];
    console.log(`[x-search] ${axis}軸: ${queries.length}クエリ`);

    for (const query of queries) {
      try {
        const tweets = await searchRecentTweets(bearerToken, query);
        if (tweets.length === 0) {
          console.log(`  (0件) ${query}`);
          continue;
        }

        // エンゲージメント上位5件に絞って Claude へ
        const top = tweets
          .sort((a, b) => (b.likes + b.retweets * 2) - (a.likes + a.retweets * 2))
          .slice(0, 5);

        const snippets = top
          .map((t) => `- [❤${t.likes} RT${t.retweets}] ${t.text.replace(/\n/g, " ")}`)
          .join("\n");

        const extraction = await client.messages.create({
          model: "claude-haiku-4-5-20251001",
          max_tokens: 800,
          messages: [{
            role: "user",
            content: `以下のX（旧Twitter）投稿からX投稿のネタになるトピックを最大3件抽出してください。
検索クエリ: "${query}"
軸: ${axis}

投稿（エンゲージメント高い順）:
${snippets}

JSON配列で出力:
[{ "theme": "テーマ", "angle": "切り口", "hint": "投稿の方向性", "bookmarkPotential": "high/medium/low" }]

除外: 宣伝のみ・根拠の薄い情報・一般論すぎる内容`,
          }],
        });

        const jsonMatch = extraction.content[0].text.match(/\[[\s\S]*\]/);
        if (!jsonMatch) continue;

        const topics = JSON.parse(jsonMatch[0]);
        const today = new Date().toISOString().slice(0, 10);

        for (const topic of topics) {
          const isDupe = seedData.seeds.some(
            (s) => s.theme === topic.theme && s.angle === topic.angle
          );
          if (isDupe) continue;

          const seed = {
            id: `seed-x-${Date.now()}-${Math.random().toString(36).slice(2, 5)}`,
            source: "x-search",
            theme: topic.theme,
            angle: topic.angle,
            hint: topic.hint,
            axis,
            types: axis === "camp" ? ["outdoor_tip", "seasonal_hook"] :
                   axis === "ai" ? ["ai_dev_log"] :
                   axis === "parenting" ? ["parenting_outdoor"] :
                   ["doc_health_tip"],
            season: [],
            used_count: 0,
            last_used: null,
            addedAt: today,
            freshUntil: new Date(Date.now() + 14 * 24 * 60 * 60 * 1000).toISOString().slice(0, 10),
            bookmarkPotential: topic.bookmarkPotential || "medium",
          };

          seedData.seeds.push(seed);
          addedCount++;
          console.log(`  + [${axis}] ${seed.theme} (${seed.bookmarkPotential})`);
        }
      } catch (err) {
        console.warn(`[x-search] エラー (${query}): ${err.message}`);
      }
    }
  }

  console.log(`[x-search] ${addedCount}件のシードを追加`);

  if (!dryRun && addedCount > 0) {
    writeJson("x-content-seeds.json", seedData);
    console.log("[x-search] x-content-seeds.json を更新しました");
  }
}

main().catch((err) => {
  console.error("[x-search] エラー:", err.message);
  process.exit(1);
});
