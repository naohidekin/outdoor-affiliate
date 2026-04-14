#!/usr/bin/env node

/**
 * 楽天ランキング リサーチソース
 *
 * 楽天市場のランキングAPIからアウトドア・キャンプジャンルの
 * トレンド商品を取得し、x-content-seeds.json にネタシードとして追加。
 *
 * 必要な環境変数:
 *   RAKUTEN_APP_ID — 楽天アプリID
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
} from "../../src/lib/x-agent-utils.mjs";

loadEnv();

// 楽天アフィリエイトID（既存products.jsonと統一）
const RAKUTEN_AFFILIATE_ID = process.env.RAKUTEN_AFFILIATE_ID || "18eb3228.621d8df3.18eb3229.ec5f8d49";

// キャンプギアカテゴリ別の検索キーワード（ランキングより検索APIの方が精度高い）
const GEAR_CATEGORIES = [
  { keyword: "キャンプ テント", name: "テント" },
  { keyword: "LEDランタン キャンプ", name: "ランタン" },
  { keyword: "アウトドアチェア キャンプ", name: "チェア" },
  { keyword: "クーラーボックス キャンプ", name: "クーラーボックス" },
  { keyword: "シュラフ 寝袋", name: "シュラフ" },
  { keyword: "焚き火台", name: "焚き火台" },
  { keyword: "キャンプ バーナー", name: "バーナー" },
  { keyword: "タープ キャンプ", name: "タープ" },
];

async function main() {
  const args = process.argv.slice(2);
  const dryRun = args.includes("--dry-run");

  const ks = checkKillSwitch();
  if (ks.killed) {
    console.error(`[rakuten-ranking] KILL SWITCH 有効: ${ks.reason}`);
    process.exit(1);
  }

  const appId = process.env.RAKUTEN_APP_ID;
  const accessKey = process.env.RAKUTEN_ACCESS_KEY;
  if (!appId) {
    console.log("[rakuten-ranking] RAKUTEN_APP_ID 未設定。スキップ。");
    return;
  }

  const seedData = readJson("x-content-seeds.json") || { seeds: [] };
  const productsData = readJson("products.json") || [];
  let addedCount = 0;
  let productsAdded = 0;
  const today = new Date().toISOString().slice(0, 10);

  for (let ci = 0; ci < GEAR_CATEGORIES.length; ci++) {
    const cat = GEAR_CATEGORIES[ci];
    // 楽天APIレート制限対策: 2リクエスト目以降は1秒待機
    if (ci > 0) await new Promise((r) => setTimeout(r, 1100));
    try {
      // 楽天商品検索API（カテゴリ別キーワード検索、レビュー件数順）
      const url = `https://openapi.rakuten.co.jp/ichibams/api/IchibaItem/Search/20220601?format=json&applicationId=${appId}${accessKey ? "&accessKey=" + accessKey : ""}&affiliateId=${RAKUTEN_AFFILIATE_ID}&keyword=${encodeURIComponent(cat.keyword)}&hits=10&sort=-reviewCount`;
      const res = await fetch(url);
      if (!res.ok) {
        console.warn(`[rakuten-ranking] API失敗 (${res.status}): ${cat.name}`);
        continue;
      }
      const data = await res.json();
      const items = data.Items || [];

      console.log(`[rakuten-ranking] ${cat.name}: ${items.length}件`);

      // 上位3件からシード生成 + products.json に商品追加
      for (const item of items.slice(0, 3)) {
        const product = item.Item || item;
        const name = product.itemName || "";
        const price = product.itemPrice;
        const reviewCount = product.reviewCount || 0;
        const reviewAvg = product.reviewAverage || 0;
        const affiliateUrl = product.affiliateUrl || "";
        const itemUrl = product.itemUrl || "";
        const imageUrl = (product.mediumImageUrls && product.mediumImageUrls[0]?.imageUrl) || "";
        const shopName = product.shopName || "";
        const itemCode = product.itemCode || "";

        if (reviewCount < 10) continue;

        const theme = `${cat.name}: ${name}`;
        const isDupe = seedData.seeds.some((s) => s.theme.includes(name.slice(0, 20)));
        if (isDupe) continue;

        // products.json に自動追加（重複チェック付き）
        const productId = `rakuten-${itemCode.replace(/[^a-zA-Z0-9-]/g, "-")}`;
        const existingProduct = productsData.find(
          (p) => p.id === productId || p.name === name.slice(0, 80)
        );
        if (!existingProduct) {
          productsData.push({
            id: productId,
            name: name.slice(0, 100),
            brand: shopName,
            price,
            imageUrl,
            affiliateUrl: affiliateUrl || itemUrl,
            amazonUrl: "",
            categoryId: cat.name,
            specs: {},
            description: `楽天レビュー${reviewCount}件、★${reviewAvg}`,
            rating: parseFloat(reviewAvg) || 0,
            createdAt: new Date().toISOString(),
            updatedAt: new Date().toISOString(),
            autoAdded: true,
            addedBy: "rakuten-ranking",
            addedAt: today,
            sourceApi: "rakuten",
          });
          productsAdded++;
        }

        const seed = {
          id: `seed-rakuten-${Date.now()}-${Math.random().toString(36).slice(2, 5)}`,
          source: "rakuten",
          theme,
          angle: `楽天ランキング上位。レビュー${reviewCount}件、評価${reviewAvg}。${price}円`,
          hint: `レビューの傾向を元に「実際どうなの？」系の投稿に。価格帯の妥当性も言及可能`,
          axis: "camp",
          types: ["outdoor_tip", "gear_thread", "article_promo"],
          season: [],
          used_count: 0,
          last_used: null,
          addedAt: today,
          freshUntil: new Date(Date.now() + 30 * 24 * 60 * 60 * 1000).toISOString().slice(0, 10),
          bookmarkPotential: reviewCount >= 100 ? "high" : "medium",
          productId,
          affiliateUrl: affiliateUrl || itemUrl,
          imageUrl,
        };

        seedData.seeds.push(seed);
        addedCount++;
        console.log(`  + ${name.slice(0, 40)} (★${reviewAvg}, ${reviewCount}件)`);
      }
    } catch (err) {
      console.warn(`[rakuten-ranking] エラー (${cat.name}): ${err.message}`);
    }
  }

  console.log(`[rakuten-ranking] ${addedCount}件のシードを追加`);
  console.log(`[rakuten-ranking] ${productsAdded}件の商品をproducts.jsonに追加`);

  if (!dryRun && addedCount > 0) {
    writeJson("x-content-seeds.json", seedData);
    console.log("[rakuten-ranking] x-content-seeds.json を更新しました");
  }
  if (!dryRun && productsAdded > 0) {
    writeJson("products.json", productsData);
    console.log("[rakuten-ranking] products.json を更新しました");
  }
}

main().catch((err) => {
  console.error("[rakuten-ranking] エラー:", err.message);
  process.exit(1);
});
