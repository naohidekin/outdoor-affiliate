#!/usr/bin/env node

/**
 * Article Product Agent — 商品調査・products.json自動追加
 *
 * article-weekly-plan.json の各テーマに対して楽天商品検索APIで商品を検索し、
 * 価格帯バランス（エントリー/ミドル/ハイエンド）で3商品を選定、
 * products.json に追加する。
 *
 * 使い方:
 *   node scripts/article-product-agent.js                  # 全テーマの商品調査
 *   node scripts/article-product-agent.js --dry-run        # 表示のみ
 *   node scripts/article-product-agent.js --theme-index 0  # 特定テーマのみ
 *
 * 必要な環境変数: RAKUTEN_APP_ID
 */

import Anthropic from "@anthropic-ai/sdk";
import {
  loadEnv,
  readJson,
  writeJson,
  checkKillSwitch,
} from "../src/lib/x-agent-utils.mjs";

loadEnv();

const RAKUTEN_API_URL = "https://openapi.rakuten.co.jp/ichibams/api/IchibaItem/Search/20220601";
const RAKUTEN_AFFILIATE_ID = "18eb3228.621d8df3.18eb3229.ec5f8d49";
const AMAZON_ASSOCIATE_TAG = "nao78-22";

// ─── CLI ─────────────────────────────────────────────

function parseArgs() {
  const args = process.argv.slice(2);
  const opts = { dryRun: false, themeIndex: null };
  for (let i = 0; i < args.length; i++) {
    switch (args[i]) {
      case "--dry-run":      opts.dryRun = true; break;
      case "--theme-index":  opts.themeIndex = parseInt(args[++i], 10); break;
    }
  }
  return opts;
}

// ─── 楽天API検索 ─────────────────────────────────────

async function searchRakuten(keyword, hits = 10) {
  const appId = process.env.RAKUTEN_APP_ID;
  const accessKey = process.env.RAKUTEN_ACCESS_KEY;
  if (!appId || !accessKey) {
    console.error("[article-product] RAKUTEN_APP_ID または RAKUTEN_ACCESS_KEY が未設定です");
    return [];
  }

  const params = new URLSearchParams({
    applicationId: appId,
    accessKey,
    affiliateId: RAKUTEN_AFFILIATE_ID,
    keyword,
    hits: String(hits),
    sort: "-reviewAverage",
    imageFlag: "1",
    formatVersion: "2",
  });

  try {
    const res = await fetch(`${RAKUTEN_API_URL}?${params}`, {
      headers: {
        "Origin": "https://camp-gear-lab.com",
        "Referer": "https://camp-gear-lab.com/",
      },
    });
    if (!res.ok) {
      const errBody = await res.text().catch(() => "");
      console.warn(`[article-product] 楽天API エラー: ${res.status} ${errBody.slice(0, 200)}`);
      return [];
    }
    const data = await res.json();
    return (data.Items || []).map((item) => ({
      itemName: item.itemName,
      itemPrice: item.itemPrice,
      itemUrl: item.itemUrl,
      affiliateUrl: item.affiliateUrl || item.itemUrl,
      imageUrl: (item.mediumImageUrls && item.mediumImageUrls[0]) || "",
      shopName: item.shopName,
      reviewAverage: item.reviewAverage || 0,
      reviewCount: item.reviewCount || 0,
      itemCaption: item.itemCaption || "",
    }));
  } catch (err) {
    console.warn(`[article-product] 楽天API エラー: ${err.message}`);
    return [];
  }
}

// ─── スペック構造化（Claude API） ────────────────────

async function extractSpecs(itemCaption, categoryId, specKeys) {
  if (!itemCaption || itemCaption.length < 20) return {};

  try {
    const anthropic = new Anthropic();
    const response = await anthropic.messages.create({
      model: "claude-haiku-4-5-20251001",
      max_tokens: 500,
      messages: [{
        role: "user",
        content: `以下の商品説明文から、指定されたスペック項目を抽出してJSONで返してください。
該当する情報がない項目は空文字にしてください。JSONのみ返してください。

スペック項目: ${specKeys.join(", ")}

商品説明:
${itemCaption.slice(0, 2000)}`,
      }],
    });

    const text = response.content[0].text.trim();
    const jsonStr = text.replace(/^```json?\s*/, "").replace(/\s*```$/, "");
    return JSON.parse(jsonStr);
  } catch {
    return {};
  }
}

// ─── 重複チェック ────────────────────────────────────

function isDuplicate(newName, existingProducts) {
  const normalize = (s) => s.toLowerCase().replace(/[\s\-　]/g, "");
  const newNorm = normalize(newName);
  return existingProducts.some((p) => {
    const existNorm = normalize(p.name);
    // 完全一致 or 一方が他方を含む
    return newNorm === existNorm || newNorm.includes(existNorm) || existNorm.includes(newNorm);
  });
}

// ─── 価格帯で3商品選定 ──────────────────────────────

function selectByPriceBand(items, count = 3) {
  if (items.length <= count) return items;

  // 価格でソート
  const sorted = [...items].sort((a, b) => a.itemPrice - b.itemPrice);

  if (count === 3) {
    // エントリー / ミドル / ハイエンド
    const entry = sorted[0];
    const high = sorted[sorted.length - 1];
    const midIdx = Math.floor(sorted.length / 2);
    const mid = sorted[midIdx];
    return [entry, mid, high];
  }

  // count != 3: 均等に分布
  const step = (sorted.length - 1) / (count - 1);
  return Array.from({ length: count }, (_, i) => sorted[Math.round(i * step)]);
}

// ─── ID生成 ──────────────────────────────────────────

function generateProductId(categoryId, existingProducts) {
  const catProducts = existingProducts.filter((p) => p.id.startsWith(categoryId + "-"));
  const maxNum = catProducts.reduce((max, p) => {
    const num = parseInt(p.id.split("-").pop(), 10);
    return num > max ? num : max;
  }, 0);
  return `${categoryId}-${String(maxNum + 1).padStart(3, "0")}`;
}

// ─── テーマ処理 ──────────────────────────────────────

async function processTheme(theme, existingProducts, categorySpecs) {
  console.log(`\n[article-product] テーマ: ${theme.title}`);

  const specKeys = categorySpecs[theme.categoryId] || [];
  const keyword = theme.targetKeywords?.[0] || theme.title.replace(/【.*】/, "").trim();

  console.log(`[article-product] 楽天検索: "${keyword}"`);
  const items = await searchRakuten(keyword, 15);

  if (items.length === 0) {
    console.warn("[article-product] 楽天APIから商品が取得できませんでした。既存商品にフォールバック。");
    const catProducts = existingProducts.filter((p) => p.categoryId === theme.categoryId);
    if (catProducts.length > 0) {
      const fallbackIds = catProducts.slice(0, 3).map((p) => p.id);
      console.log(`[article-product] 既存商品を使用: ${fallbackIds.join(", ")}`);
      return { products: [], productIds: fallbackIds };
    }
    return { products: [], productIds: [] };
  }

  console.log(`[article-product] 候補: ${items.length}件`);

  // 重複除外
  const uniqueItems = items.filter((item) => !isDuplicate(item.itemName, existingProducts));
  console.log(`[article-product] 重複除外後: ${uniqueItems.length}件`);

  if (uniqueItems.length === 0) {
    console.warn("[article-product] 全候補が既存商品と重複");
    // 既存商品から同カテゴリのものを使う
    const catProducts = existingProducts.filter((p) => p.categoryId === theme.categoryId);
    return {
      products: [],
      productIds: catProducts.slice(0, 3).map((p) => p.id),
    };
  }

  // 価格帯で3商品選定
  const selected = selectByPriceBand(uniqueItems, 3);

  // 各商品をproducts.json形式に変換
  const newProducts = [];
  for (const item of selected) {
    const specs = await extractSpecs(item.itemCaption, theme.categoryId, specKeys);

    const productId = generateProductId(theme.categoryId, [...existingProducts, ...newProducts]);
    const amazonSearchUrl = `https://www.amazon.co.jp/s?k=${encodeURIComponent(item.itemName)}&tag=${AMAZON_ASSOCIATE_TAG}`;

    newProducts.push({
      id: productId,
      name: item.itemName.slice(0, 100), // 長すぎる名前を切り詰め
      brand: item.shopName || "",
      price: item.itemPrice,
      imageUrl: item.imageUrl,
      affiliateUrl: item.affiliateUrl,
      amazonUrl: amazonSearchUrl,
      categoryId: theme.categoryId,
      specs,
      description: "",
      rating: item.reviewAverage || 0,
      createdAt: new Date().toISOString(),
      updatedAt: new Date().toISOString(),
      autoAdded: true,
      addedBy: "article-product-agent",
      addedAt: new Date().toISOString(),
      sourceApi: "rakuten",
    });

    console.log(`  + ${item.itemName.slice(0, 50)}... (¥${item.itemPrice})`);
  }

  return {
    products: newProducts,
    productIds: newProducts.map((p) => p.id),
  };
}

// ─── メイン ──────────────────────────────────────────

async function main() {
  const opts = parseArgs();

  const ks = checkKillSwitch();
  if (ks.killed) {
    console.error(`[article-product] KILL SWITCH 有効: ${ks.reason}`);
    process.exit(1);
  }
  const ksData = readJson("kill-switch.json");
  if (ksData?.articleEnabled) {
    console.error("[article-product] 記事パイプライン Kill Switch 有効。中止。");
    process.exit(1);
  }

  const plan = readJson("article-weekly-plan.json");
  if (!plan || !plan.articles || plan.articles.length === 0) {
    console.error("[article-product] article-weekly-plan.json がないか空です");
    process.exit(1);
  }

  const categorySpecs = readJson("category-specs.json") || {};
  let existingProducts = readJson("products.json") || [];

  const themes = opts.themeIndex != null
    ? [plan.articles[opts.themeIndex]].filter(Boolean)
    : plan.articles;

  console.log(`[article-product] ${themes.length}テーマの商品調査を開始`);

  // 各テーマの商品リストを plan に追記
  for (let i = 0; i < themes.length; i++) {
    const theme = themes[i];

    // 楽天API レート制限回避（1秒間隔）
    if (i > 0) await new Promise((r) => setTimeout(r, 1200));

    const result = await processTheme(theme, existingProducts, categorySpecs);

    // plan に productIds を記録
    theme.productIds = result.productIds;

    if (!opts.dryRun && result.products.length > 0) {
      // products.json に追加
      existingProducts = [...existingProducts, ...result.products];
      writeJson("products.json", existingProducts);
      console.log(`[article-product] products.json に ${result.products.length}件追加`);
    } else if (opts.dryRun) {
      console.log(`[DRY RUN] ${result.products.length}件の商品追加をスキップ`);
    }
  }

  // plan を更新（productIds 付き）
  if (!opts.dryRun) {
    writeJson("article-weekly-plan.json", plan);
    console.log("[article-product] article-weekly-plan.json を更新しました（productIds付与）");
  }

  console.log("\n[article-product] 商品調査完了");
}

main().catch((err) => {
  console.error("[article-product] エラー:", err.message);
  process.exit(1);
});
