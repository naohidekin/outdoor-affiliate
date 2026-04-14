#!/usr/bin/env node

/**
 * Google検索トレンド リサーチソース
 *
 * Googleの検索結果からキャンプ・アウトドア関連のトレンドネタを収集し、
 * x-content-seeds.json に追加する。
 *
 * 必要な環境変数:
 *   GOOGLE_CUSTOM_SEARCH_KEY — Google Custom Search API キー
 *   GOOGLE_CUSTOM_SEARCH_CX  — カスタム検索エンジンID
 *   ANTHROPIC_API_KEY         — Claude API キー（ネタ抽出用）
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

// ─── メイン ──────────────────────────────────────────

async function main() {
  const args = process.argv.slice(2);
  const dryRun = args.includes("--dry-run");
  const axisArg = args.find((a, i) => args[i - 1] === "--axis");

  const ks = checkKillSwitch();
  if (ks.killed) {
    console.error(`[google-trends] KILL SWITCH 有効: ${ks.reason}`);
    process.exit(1);
  }

  const apiKey = process.env.GOOGLE_CUSTOM_SEARCH_KEY;
  const cx = process.env.GOOGLE_CUSTOM_SEARCH_CX;

  if (!apiKey || !cx) {
    console.log("[google-trends] GOOGLE_CUSTOM_SEARCH_KEY / CX 未設定。スキップ。");
    return;
  }

  const anthropicKey = process.env.ANTHROPIC_API_KEY;
  if (!anthropicKey) {
    console.error("[google-trends] ANTHROPIC_API_KEY 未設定");
    process.exit(1);
  }

  const Anthropic = (await import("@anthropic-ai/sdk")).default;
  const client = new Anthropic({ apiKey: anthropicKey, fetch: ipv4Fetch, maxRetries: 3 });

  const seedData = readJson("x-content-seeds.json") || { seeds: [] };
  const axes = axisArg ? [axisArg] : Object.keys(SEARCH_QUERIES);

  let addedCount = 0;

  for (const axis of axes) {
    const queries = SEARCH_QUERIES[axis] || [];
    console.log(`[google-trends] ${axis}軸: ${queries.length}クエリ`);

    for (const query of queries) {
      try {
        // Google Custom Search API
        const url = `https://www.googleapis.com/customsearch/v1?key=${apiKey}&cx=${cx}&q=${encodeURIComponent(query)}&num=5&lr=lang_ja&dateRestrict=m3`;
        const res = await fetch(url);
        if (!res.ok) {
          console.warn(`[google-trends] 検索失敗 (${res.status}): ${query}`);
          continue;
        }
        const data = await res.json();
        const items = data.items || [];

        if (items.length === 0) continue;

        // Claude でネタ抽出
        const snippets = items.map((item) => `- ${item.title}: ${item.snippet}`).join("\n");
        const extraction = await client.messages.create({
          model: "claude-sonnet-4-20250514",
          max_tokens: 1000,
          messages: [{
            role: "user",
            content: `以下のGoogle検索結果からX投稿のネタになるトピックを最大3件抽出してください。
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
          // 重複チェック
          const isDupe = seedData.seeds.some(
            (s) => s.theme === topic.theme && s.angle === topic.angle
          );
          if (isDupe) continue;

          const seed = {
            id: `seed-google-${Date.now()}-${Math.random().toString(36).slice(2, 5)}`,
            source: "google",
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
        console.warn(`[google-trends] エラー (${query}): ${err.message}`);
      }
    }
  }

  console.log(`[google-trends] ${addedCount}件のシードを追加`);

  if (!dryRun && addedCount > 0) {
    writeJson("x-content-seeds.json", seedData);
    console.log("[google-trends] x-content-seeds.json を更新しました");
  }
}

main().catch((err) => {
  console.error("[google-trends] エラー:", err.message);
  process.exit(1);
});
