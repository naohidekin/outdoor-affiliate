#!/usr/bin/env node

/**
 * Brave Search リサーチソース（旧: Google Custom Search）
 *
 * Brave Search APIからキャンプ・アウトドア関連のトレンドネタを収集し、
 * x-content-seeds.json に追加する。
 *
 * 必要な環境変数:
 *   BRAVE_API_KEY     — Brave Search API キー
 *   ANTHROPIC_API_KEY — Claude API キー（ネタ抽出用）
 *
 * 使い方:
 *   node scripts/research-sources/google-trends.js
 *   node scripts/research-sources/google-trends.js --dry-run
 *   node scripts/research-sources/google-trends.js --axis camp
 */

import {
  loadEnv,
  readJson,
  writeJson,
  checkKillSwitch,
  ipv4Fetch,
} from "../../src/lib/x-agent-utils.mjs";

loadEnv();

// ─── 検索キーワード定義（テーマツリー連動）───────────

const SEARCH_QUERIES = {
  camp: [
    "キャンプ 新商品 2026",
    "キャンプギア レビュー 最新",
    "ファミリーキャンプ コツ",
    "ソロキャンプ 道具 おすすめ",
    "キャンプ場 穴場",
  ],
  ai: [
    "Claude Code 使い方",
    "AI 個人開発",
    "生成AI 活用事例",
  ],
  parenting: [
    "子連れ キャンプ 持ち物",
    "ファミキャン 初心者",
    "子供 アウトドア 体験",
  ],
  doctor: [
    "キャンプ 怪我 応急処置",
    "アウトドア 熱中症 対策",
    "虫刺され 正しい対処",
  ],
};

// ─── Brave Search API ─────────────────────────────────

async function braveSearch(apiKey, query, count = 5) {
  const url = `https://api.search.brave.com/res/v1/web/search?q=${encodeURIComponent(query)}&count=${count}&country=JP`;
  const res = await fetch(url, {
    headers: {
      "Accept": "application/json",
      "Accept-Encoding": "gzip",
      "X-Subscription-Token": apiKey,
    },
  });
  if (!res.ok) {
    throw new Error(`Brave Search 失敗 (${res.status}): ${query}`);
  }
  const data = await res.json();
  return (data.web?.results || []).map((r) => ({
    title: r.title,
    snippet: r.description || "",
    url: r.url,
  }));
}

// ─── メイン ──────────────────────────────────────────

async function main() {
  const args = process.argv.slice(2);
  const dryRun = args.includes("--dry-run");
  const axisArg = args.find((a, i) => args[i - 1] === "--axis");

  const ks = checkKillSwitch();
  if (ks.killed) {
    console.error(`[brave-search] KILL SWITCH 有効: ${ks.reason}`);
    process.exit(1);
  }

  const apiKey = process.env.BRAVE_API_KEY;
  if (!apiKey) {
    console.log("[brave-search] BRAVE_API_KEY 未設定。スキップ。");
    return;
  }

  const anthropicKey = process.env.ANTHROPIC_API_KEY;
  if (!anthropicKey) {
    console.error("[brave-search] ANTHROPIC_API_KEY 未設定");
    process.exit(1);
  }

  const Anthropic = (await import("@anthropic-ai/sdk")).default;
  const client = new Anthropic({ apiKey: anthropicKey, fetch: ipv4Fetch, maxRetries: 3 });

  const seedData = readJson("x-content-seeds.json") || { seeds: [] };
  const axes = axisArg ? [axisArg] : Object.keys(SEARCH_QUERIES);

  let addedCount = 0;

  for (const axis of axes) {
    const queries = SEARCH_QUERIES[axis] || [];
    console.log(`[brave-search] ${axis}軸: ${queries.length}クエリ`);

    for (const query of queries) {
      try {
        const items = await braveSearch(apiKey, query);
        if (items.length === 0) continue;

        // Claude でネタ抽出
        const snippets = items.map((item) => `- ${item.title}: ${item.snippet}`).join("\n");
        const extraction = await client.messages.create({
          model: "claude-haiku-4-5-20251001",
          max_tokens: 800,
          messages: [{
            role: "user",
            content: `以下の検索結果からX投稿のネタになるトピックを最大3件抽出してください。
検索クエリ: "${query}"
軸: ${axis}

検索結果:
${snippets}

JSON配列で出力:
[{ "theme": "テーマ", "angle": "切り口", "hint": "投稿の方向性", "bookmarkPotential": "high/medium/low" }]

除外: 一般常識、宣伝のみの内容、根拠の薄い情報`,
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
            id: `seed-brave-${Date.now()}-${Math.random().toString(36).slice(2, 5)}`,
            source: "brave",
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
            freshUntil: new Date(Date.now() + 60 * 24 * 60 * 60 * 1000).toISOString().slice(0, 10),
            bookmarkPotential: topic.bookmarkPotential || "medium",
          };

          seedData.seeds.push(seed);
          addedCount++;
          console.log(`  + [${axis}] ${seed.theme} (${seed.bookmarkPotential})`);
        }
      } catch (err) {
        console.warn(`[brave-search] エラー (${query}): ${err.message}`);
      }
    }
  }

  console.log(`[brave-search] ${addedCount}件のシードを追加`);

  if (!dryRun && addedCount > 0) {
    writeJson("x-content-seeds.json", seedData);
    console.log("[brave-search] x-content-seeds.json を更新しました");
  }
}

main().catch((err) => {
  console.error("[brave-search] エラー:", err.message);
  process.exit(1);
});
