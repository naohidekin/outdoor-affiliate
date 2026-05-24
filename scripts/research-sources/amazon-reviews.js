#!/usr/bin/env node

/**
 * Amazon レビュー リサーチソース
 *
 * products.json に登録済みの商品のAmazon ASINを使い、
 * Product Advertising API (PA-API 5.0) でレビュー情報を取得。
 * 話題の商品や評価の高い/低い商品からネタシードを生成。
 *
 * 必要な環境変数:
 *   AMAZON_ACCESS_KEY — PA-API アクセスキー
 *   AMAZON_SECRET_KEY — PA-API シークレットキー
 *   AMAZON_PARTNER_TAG — アソシエイトタグ (camp78-22)
 *
 * 使い方:
 *   node scripts/research-sources/amazon-reviews.js
 *   node scripts/research-sources/amazon-reviews.js --dry-run
 *
 * 注意: PA-API は売上に基づいてレート制限が設定されるため、
 *       過度なリクエストは避ける。1回の実行で最大10商品。
 */

import {
  loadEnv,
  readJson,
  writeJson,
  checkKillSwitch,
} from "../../src/lib/x-agent-utils.mjs";

loadEnv();

async function main() {
  const args = process.argv.slice(2);
  const dryRun = args.includes("--dry-run");

  const ks = checkKillSwitch();
  if (ks.killed) {
    console.error(`[amazon-reviews] KILL SWITCH 有効: ${ks.reason}`);
    process.exit(1);
  }

  const accessKey = process.env.AMAZON_ACCESS_KEY;
  const secretKey = process.env.AMAZON_SECRET_KEY;
  const partnerTag = process.env.AMAZON_PARTNER_TAG || "camp78-22";

  if (!accessKey || !secretKey) {
    console.log("[amazon-reviews] AMAZON_ACCESS_KEY / SECRET_KEY 未設定。スキップ。");
    return;
  }

  // products.json から ASIN を持つ商品を取得
  const products = readJson("products.json") || [];
  const withAsin = products.filter((p) => p.amazonUrl);
  const asins = withAsin
    .map((p) => {
      const match = p.amazonUrl.match(/\/dp\/([A-Z0-9]{10})/);
      return match ? { asin: match[1], name: p.name, category: p.categoryId } : null;
    })
    .filter(Boolean)
    .slice(0, 10); // PA-API レート制限考慮

  if (asins.length === 0) {
    console.log("[amazon-reviews] ASIN付き商品なし。スキップ。");
    return;
  }

  console.log(`[amazon-reviews] ${asins.length}件の商品を確認`);

  // TODO: PA-API 5.0 の署名付きリクエスト実装
  // 現時点では products.json のデータからシードを生成
  const seedData = readJson("x-content-seeds.json") || { seeds: [] };
  let addedCount = 0;
  const today = new Date().toISOString().slice(0, 10);

  for (const item of asins) {
    const theme = `Amazon商品分析: ${item.name}`;
    const isDupe = seedData.seeds.some((s) => s.theme.includes(item.name.slice(0, 20)));
    if (isDupe) continue;

    const seed = {
      id: `seed-amazon-${Date.now()}-${Math.random().toString(36).slice(2, 5)}`,
      source: "amazon",
      theme,
      angle: `Amazon ASIN ${item.asin} のレビュー傾向を元に比較・解説`,
      hint: `「実際に使ってみた系」「レビューのここが本当か検証」系の投稿に`,
      axis: "camp",
      types: ["outdoor_tip", "gear_thread"],
      season: [],
      used_count: 0,
      last_used: null,
      addedAt: today,
      freshUntil: new Date(Date.now() + 60 * 24 * 60 * 60 * 1000).toISOString().slice(0, 10),
      bookmarkPotential: "medium",
    };

    seedData.seeds.push(seed);
    addedCount++;
    console.log(`  + ${item.name.slice(0, 40)} (${item.asin})`);
  }

  console.log(`[amazon-reviews] ${addedCount}件のシードを追加`);

  if (!dryRun && addedCount > 0) {
    writeJson("x-content-seeds.json", seedData);
    console.log("[amazon-reviews] x-content-seeds.json を更新しました");
  }
}

main().catch((err) => {
  console.error("[amazon-reviews] エラー:", err.message);
  process.exit(1);
});
