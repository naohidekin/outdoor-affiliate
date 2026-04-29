#!/usr/bin/env node

/**
 * 楽天商品リサーチソース（Brave Search版）
 *
 * Brave Search で site:item.rakuten.co.jp を使い、
 * キャンプ・アウトドアジャンルの人気商品を収集して
 * x-content-seeds.json と products.json に追加する。
 *
 * 必要な環境変数:
 *   BRAVE_API_KEY     — Brave Search API キー
 *   ANTHROPIC_API_KEY — Claude API キー
 *
 * 使い方:
 *   node scripts/research-sources/rakuten-ranking.js
 *   node scripts/research-sources/rakuten-ranking.js --dry-run
 */

import {
  loadEnv,
  readJson,
  writeJson,
  checkKillSwitch,
  ipv4Fetch,
} from "../../src/lib/x-agent-utils.mjs";

loadEnv();

const RAKUTEN_AFFILIATE_ID = process.env.RAKUTEN_AFFILIATE_ID || "18eb3228.621d8df3.18eb3229.ec5f8d49";

// 通年カテゴリ
const BASE_CATEGORIES = [
  { keyword: "キャンプ テント", name: "テント" },
  { keyword: "LEDランタン キャンプ", name: "ランタン" },
  { keyword: "アウトドアチェア キャンプ", name: "チェア" },
  { keyword: "焚き火台 アウトドア", name: "焚き火台" },
  { keyword: "タープ キャンプ", name: "タープ" },
];

// 季節別追加カテゴリ
const SEASONAL_CATEGORIES = {
  spring: [ // 3-5月
    { keyword: "キャンプ バーナー ストーブ", name: "バーナー" },
    { keyword: "キャンプ テーブル 折りたたみ", name: "テーブル" },
    { keyword: "虫除け キャンプ アウトドア", name: "虫除け" },
  ],
  summer: [ // 6-8月
    { keyword: "クーラーボックス キャンプ", name: "クーラーボックス" },
    { keyword: "ハンモック キャンプ", name: "ハンモック" },
    { keyword: "ポータブル扇風機 アウトドア", name: "ポータブル扇風機" },
  ],
  autumn: [ // 9-11月
    { keyword: "シュラフ 寝袋 キャンプ", name: "シュラフ" },
    { keyword: "焚き火 薪 キャンプ", name: "薪・着火" },
    { keyword: "キャンプ 防寒 アウトドア", name: "防寒ウェア" },
  ],
  winter: [ // 12-2月
    { keyword: "シュラフ 寝袋 冬用 キャンプ", name: "冬用シュラフ" },
    { keyword: "ストーブ キャンプ 暖房", name: "暖房器具" },
    { keyword: "スキー ウェア アウトドア", name: "スキーウェア" },
  ],
};

function getSeasonalCategories() {
  const month = new Date().getMonth() + 1;
  let season;
  if (month >= 3 && month <= 5) season = "spring";
  else if (month >= 6 && month <= 8) season = "summer";
  else if (month >= 9 && month <= 11) season = "autumn";
  else season = "winter";
  return [...BASE_CATEGORIES, ...SEASONAL_CATEGORIES[season]];
}

const GEAR_CATEGORIES = getSeasonalCategories();

// ─── Brave Search（楽天サイト絞り込み）─────────────────

async function braveSearchRakuten(apiKey, keyword, count = 5) {
  const query = `${keyword} site:item.rakuten.co.jp`;
  const url = `https://api.search.brave.com/res/v1/web/search?q=${encodeURIComponent(query)}&count=${count}&country=JP`;
  const res = await fetch(url, {
    headers: {
      Accept: "application/json",
      "Accept-Encoding": "gzip",
      "X-Subscription-Token": apiKey,
    },
  });
  if (!res.ok) throw new Error(`Brave Search 失敗 (${res.status}): ${keyword}`);
  const data = await res.json();
  return (data.web?.results || [])
    .filter((r) => r.url.includes("item.rakuten.co.jp"))
    .map((r) => ({
      title: r.title,
      snippet: r.description || "",
      url: r.url,
    }));
}

// 楽天アイテムURLからアフィリエイトURLを生成
function buildAffiliateUrl(itemUrl) {
  return `https://hb.afl.rakuten.co.jp/ichiba/${RAKUTEN_AFFILIATE_ID}/?pc=${encodeURIComponent(itemUrl)}&link_type=text&ut=eyJwYWdlIjoiaXRlbSIsInR5cGUiOiJ0ZXh0Iiwic2l6ZSI6IjI0MHgyNDAiLCJuYW0iOjEsIm5hbXAiOiJyaWdodCIsImNvbSI6MSwiY29tcCI6ImRvd24iLCJwcmljZSI6MSwiYm9yIjoxLCJjb2wiOjEsImJidG4iOjEsInByb2QiOjAsImFtcCI6ZmFsc2V9`;
}

// ─── メイン ──────────────────────────────────────────

async function main() {
  const args = process.argv.slice(2);
  const dryRun = args.includes("--dry-run");

  const ks = checkKillSwitch();
  if (ks.killed) {
    console.error(`[rakuten-brave] KILL SWITCH 有効: ${ks.reason}`);
    process.exit(1);
  }

  const apiKey = process.env.BRAVE_API_KEY;
  if (!apiKey) {
    console.log("[rakuten-brave] BRAVE_API_KEY 未設定。スキップ。");
    return;
  }

  const anthropicKey = process.env.ANTHROPIC_API_KEY;
  if (!anthropicKey) {
    console.error("[rakuten-brave] ANTHROPIC_API_KEY 未設定");
    process.exit(1);
  }

  const Anthropic = (await import("@anthropic-ai/sdk")).default;
  const client = new Anthropic({ apiKey: anthropicKey, fetch: ipv4Fetch, maxRetries: 3 });

  const seedData = readJson("x-content-seeds.json") || { seeds: [] };
  const productsData = readJson("products.json") || [];
  const today = new Date().toISOString().slice(0, 10);
  let addedSeeds = 0;
  let addedProducts = 0;

  for (let ci = 0; ci < GEAR_CATEGORIES.length; ci++) {
    const cat = GEAR_CATEGORIES[ci];
    if (ci > 0) await new Promise((r) => setTimeout(r, 1000));

    try {
      const items = await braveSearchRakuten(apiKey, cat.keyword);
      if (items.length === 0) {
        console.log(`[rakuten-brave] ${cat.name}: 0件`);
        continue;
      }
      console.log(`[rakuten-brave] ${cat.name}: ${items.length}件`);

      // Claude で商品情報・ネタ抽出
      const snippets = items
        .map((it) => `- タイトル: ${it.title}\n  説明: ${it.snippet}\n  URL: ${it.url}`)
        .join("\n");

      const extraction = await client.messages.create({
        model: "claude-haiku-4-5-20251001",
        max_tokens: 1000,
        messages: [{
          role: "user",
          content: `以下は楽天市場の「${cat.name}」カテゴリの商品検索結果です。
上位2件の商品情報を抽出し、X投稿ネタも生成してください。

検索結果:
${snippets}

JSON形式で出力:
{
  "products": [
    {
      "name": "商品名（簡潔に、100文字以内）",
      "price": "価格（スニペットから読み取れれば数値、不明なら0）",
      "url": "元のURL",
      "description": "商品特徴の要約（50文字以内）"
    }
  ],
  "seeds": [
    {
      "theme": "テーマ",
      "angle": "切り口",
      "hint": "投稿の方向性",
      "bookmarkPotential": "high/medium/low"
    }
  ]
}

注意: priceは整数のみ（円マーク不要）。URLはそのまま転記。`,
        }],
      });

      const jsonMatch = extraction.content[0].text.match(/\{[\s\S]*\}/);
      if (!jsonMatch) continue;

      const result = JSON.parse(jsonMatch[0]);

      // products.json に追加（重複チェック強化）
      for (const p of (result.products || [])) {
        if (!p.url || !p.name) continue;
        const productId = `rakuten-brave-${ci}-${p.url.split("/").slice(-2, -1)[0] || Date.now()}`;
        // 正規化: スペース・記号を除去して比較（「スノーピーク ランドロック」≒「スノーピークランドロック」）
        const normalize = (s) => (s || "").replace(/[\s\-・　]/g, "").toLowerCase().slice(0, 60);
        const newNorm = normalize(p.name);
        const exists = productsData.find((x) =>
          x.id === productId ||
          x.name === p.name.slice(0, 80) ||
          normalize(x.name) === newNorm
        );
        if (!exists) {
          const affiliateUrl = buildAffiliateUrl(p.url);
          productsData.push({
            id: productId,
            name: p.name.slice(0, 100),
            brand: "",
            price: typeof p.price === "number" ? p.price : parseInt(p.price) || 0,
            imageUrl: "",
            affiliateUrl,
            amazonUrl: "",
            categoryId: cat.name,
            specs: {},
            description: p.description || "",
            rating: 0,
            createdAt: new Date().toISOString(),
            updatedAt: new Date().toISOString(),
            autoAdded: true,
            addedBy: "rakuten-brave",
            addedAt: today,
            sourceApi: "brave-rakuten",
          });
          addedProducts++;
        }
      }

      // seeds に追加
      for (const topic of (result.seeds || [])) {
        const isDupe = seedData.seeds.some(
          (s) => s.theme === topic.theme && s.angle === topic.angle
        );
        if (isDupe) continue;

        seedData.seeds.push({
          id: `seed-rakuten-${Date.now()}-${Math.random().toString(36).slice(2, 5)}`,
          source: "rakuten-brave",
          theme: topic.theme,
          angle: topic.angle,
          hint: topic.hint,
          axis: "camp",
          types: ["outdoor_tip", "gear_thread", "article_promo"],
          season: [],
          used_count: 0,
          last_used: null,
          addedAt: today,
          freshUntil: new Date(Date.now() + 30 * 24 * 60 * 60 * 1000).toISOString().slice(0, 10),
          bookmarkPotential: topic.bookmarkPotential || "medium",
        });
        addedSeeds++;
        console.log(`  + ${topic.theme} (${topic.bookmarkPotential})`);
      }
    } catch (err) {
      console.warn(`[rakuten-brave] エラー (${cat.name}): ${err.message}`);
    }
  }

  console.log(`[rakuten-brave] シード ${addedSeeds}件、商品 ${addedProducts}件を追加`);

  if (!dryRun) {
    if (addedSeeds > 0) {
      writeJson("x-content-seeds.json", seedData);
      console.log("[rakuten-brave] x-content-seeds.json を更新しました");
    }
    if (addedProducts > 0) {
      writeJson("products.json", productsData);
      console.log("[rakuten-brave] products.json を更新しました");
    }
  }
}

main().catch((err) => {
  console.error("[rakuten-brave] エラー:", err.message);
  process.exit(1);
});
