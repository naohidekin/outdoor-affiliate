#!/usr/bin/env node

/**
 * Amazon 価格監視 & セール検知スクリプト
 * Creators API で商品価格を取得し、値下げ・セールを検知
 * → 検知時に X投稿を自動生成してGoogle Sheetsに保存
 *
 * ※ PA-API v5 は 2026-05-15 に廃止。後継の Creators API に移行済み。
 *
 * 必要な環境変数:
 *   AMAZON_CREDENTIAL_ID      — 認証情報ID (amzn1.application-oa2-client....)
 *   AMAZON_CREDENTIAL_SECRET  — 発行時に一度だけ表示されるSecret
 *   AMAZON_PARTNER_TAG        — アソシエイトタグ (既定: camp78-22)
 *   ※ 旧 AMAZON_ACCESS_KEY / AMAZON_SECRET_KEY に入っていても読む
 *
 * 使い方:
 *   node scripts/price-monitor.js
 *   node scripts/price-monitor.js --threshold=15  (15%以上の値下げのみ通知)
 */

import fs from "fs";
import path from "path";
import { fileURLToPath } from "url";
import { creatorsApi, credentials, hasCredentials } from "../src/lib/amazon-creators-api.mjs";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const DATA_DIR = path.join(__dirname, "..", "data");

// .env.local を手動読み込み
const envPath = path.join(__dirname, "..", ".env.local");
if (fs.existsSync(envPath)) {
  const envContent = fs.readFileSync(envPath, "utf-8");
  for (const line of envContent.split("\n")) {
    const match = line.match(/^([^#=]+)=(.*)$/);
    if (match && !process.env[match[1].trim()]) {
      process.env[match[1].trim()] = match[2].trim();
    }
  }
}

const THRESHOLD = parseInt(
  process.argv.find((a) => a.startsWith("--threshold="))?.split("=")[1] || "10"
);

// --- Creators API（PA-API v5 は 2026-05-15 廃止） ---
// 認証・トークン管理・429リトライは src/lib/amazon-creators-api.mjs に集約

// --- 価格取得 ---

function extractAsin(url) {
  const match = url.match(/\/dp\/([A-Z0-9]{10})/);
  return match ? match[1] : null;
}

// offersV2 に定価（savingBasis）が含まれるかは環境によって差があるため、
// richリソースで一度試し、拒否されたら最小構成に落として続行する。
// 最小構成でも「保存済み価格からの下落」は検知できる（定価比だけが取れなくなる）。
const RESOURCES_RICH = [
  "itemInfo.title",
  "offersV2.listings.price",
  "offersV2.listings.savingBasis",
];
const RESOURCES_MIN = ["itemInfo.title", "offersV2.listings.price"];
let resources = RESOURCES_RICH;
let savingBasisAvailable = true;

async function getItemPrices(asins) {
  const c = credentials();
  let data;
  try {
    data = await creatorsApi("/catalog/v1/getItems", {
      itemIds: asins,
      partnerTag: c.partnerTag,
      resources,
    });
  } catch (e) {
    // 未対応リソースが原因なら最小構成へ落として再試行する（一度だけ）
    if (resources === RESOURCES_RICH && /400|resource/i.test(String(e.message))) {
      console.log("  ℹ️ savingBasis 非対応のため最小リソースに切替（定価比の検知は無効）");
      resources = RESOURCES_MIN;
      savingBasisAvailable = false;
      data = await creatorsApi("/catalog/v1/getItems", {
        itemIds: asins,
        partnerTag: c.partnerTag,
        resources,
      });
    } else {
      throw e;
    }
  }

  for (const e of data.errors || []) {
    console.log(`  ⚠️ APIエラー: ${e.code} ${String(e.message).slice(0, 100)}`);
  }

  // 既存の集計ロジックを変えずに済むよう、PA-API v5 と同じ形に整形して返す
  return (data.itemsResult?.items || []).map((item) => {
    const listing = item.offersV2?.listings?.[0];
    const amount = listing?.price?.money?.amount;
    const basis = listing?.savingBasis?.money?.amount;
    const savings =
      basis && amount && basis > amount
        ? { Amount: Math.round(basis - amount), Percentage: Math.round(((basis - amount) / basis) * 100) }
        : undefined;
    return {
      ASIN: item.asin,
      ItemInfo: { Title: { DisplayValue: item.itemInfo?.title?.displayValue || "" } },
      Offers: {
        Listings: listing
          ? [
              {
                Price: { Amount: typeof amount === "number" ? Math.round(amount) : undefined, Savings: savings },
                SavingBasis: basis ? { Amount: Math.round(basis) } : undefined,
              },
            ]
          : [],
      },
    };
  });
}

// --- メイン処理 ---

let priceUpdateCount = 0; // 完走後のSupabase同期ゲート用

async function main() {
  if (!hasCredentials()) {
    console.log("⚠️ Creators API認証情報が未設定です。");
    console.log("");
    console.log("以下を .env.local に追加してください:");
    console.log("  AMAZON_CREDENTIAL_ID=amzn1.application-oa2-client....");
    console.log("  AMAZON_CREDENTIAL_SECRET=（発行時に一度だけ表示されるSecret）");
    console.log("  # AMAZON_PARTNER_TAG=camp78-22   … 未設定なら既定値を使用");
    console.log("");
    console.log("認証情報の取得方法:");
    console.log("  1. https://affiliate.amazon.co.jp/ にログイン");
    console.log("  2. ツール → クリエイターAPI（/creatorsapi）");
    console.log("  3. アプリケーションの「新しい認証情報を追加」");
    console.log("     → Secret は追加直後にしか表示されないので必ず控える");
    console.log("");
    console.log("※ PA API へのアクセスには、過去30日間に10件以上の売上が必要です");
    console.log("※ 旧 AMAZON_ACCESS_KEY / AMAZON_SECRET_KEY に入れてあっても読みます");
    process.exit(0);
  }

  const products = JSON.parse(
    fs.readFileSync(path.join(DATA_DIR, "products.json"), "utf-8")
  );

  // 価格履歴ファイル読み込み
  const priceHistoryPath = path.join(DATA_DIR, "price-history.json");
  let priceHistory = {};
  if (fs.existsSync(priceHistoryPath)) {
    priceHistory = JSON.parse(fs.readFileSync(priceHistoryPath, "utf-8"));
  }

  // ASIN抽出
  const productAsins = products
    .filter((p) => p.amazonUrl)
    .map((p) => ({ ...p, asin: extractAsin(p.amazonUrl) }))
    .filter((p) => p.asin);

  console.log(`\n💰 価格監視開始（${productAsins.length}件）`);
  console.log(`📉 値下げ検知しきい値: ${THRESHOLD}%\n`);

  const deals = [];
  const priceUpdates = {};

  // 10件ずつバッチ処理（PA-API制限）
  for (let i = 0; i < productAsins.length; i += 10) {
    const batch = productAsins.slice(i, i + 10);
    const asins = batch.map((p) => p.asin);

    try {
      const items = await getItemPrices(asins);

      for (const item of items) {
        const asin = item.ASIN;
        const product = batch.find((p) => p.asin === asin);
        if (!product) continue;

        const listing = item.Offers?.Listings?.[0];
        if (!listing) continue;

        const currentPrice = listing.Price?.Amount;
        const savingBasis = listing.SavingBasis?.Amount; // 定価/通常価格
        const savedPrice = listing.Price?.Savings?.Amount;
        const savedPct = listing.Price?.Savings?.Percentage;

        if (!currentPrice) continue;

        // 価格履歴に記録
        const prevPrice = priceHistory[asin]?.price || product.price;
        priceUpdates[asin] = {
          price: currentPrice,
          checkedAt: new Date().toISOString(),
          previousPrice: prevPrice,
        };

        // 値下げ検知
        const dropFromStored = prevPrice > 0
          ? Math.round(((prevPrice - currentPrice) / prevPrice) * 100)
          : 0;
        const dropFromList = savedPct || 0;

        const isOnSale = dropFromList >= THRESHOLD || dropFromStored >= THRESHOLD;

        if (isOnSale) {
          deals.push({
            product,
            asin,
            currentPrice,
            previousPrice: prevPrice,
            listPrice: savingBasis || prevPrice,
            dropPct: Math.max(dropFromList, dropFromStored),
            savedAmount: savedPrice || prevPrice - currentPrice,
          });
          console.log(
            `  🔥 ${product.name.slice(0, 30)} ¥${prevPrice.toLocaleString()} → ¥${currentPrice.toLocaleString()} (${Math.max(dropFromList, dropFromStored)}%OFF)`
          );
        } else {
          console.log(
            `  ✅ ${product.name.slice(0, 30)} ¥${currentPrice.toLocaleString()}`
          );
        }

        // products.json の価格も更新。productは .map(p => ({...p})) の浅いコピーなので
        // 必ず原本(products配列)側を更新する（コピーだけ更新すると書き出しに反映されない）
        const original = products.find((p) => p.id === product.id);
        if (original) {
          const ts = new Date().toISOString();
          original.price = currentPrice;
          original.priceUpdatedAt = ts;
          // pull時のマージは updatedAt 比較でローカル/リモートを選ぶため、
          // これを進めないと次回同期で旧価格に巻き戻される
          original.updatedAt = ts;
        }
      }
    } catch (err) {
      console.error(`  ❌ バッチ ${i / 10 + 1} エラー: ${err.message}`);
    }

    // レート制限（PA-APIは1秒1リクエスト）
    if (i + 10 < productAsins.length) {
      await new Promise((r) => setTimeout(r, 1500));
    }
  }

  // 価格履歴保存
  Object.assign(priceHistory, priceUpdates);
  fs.writeFileSync(priceHistoryPath, JSON.stringify(priceHistory, null, 2), "utf-8");

  // products.jsonの価格更新
  priceUpdateCount = Object.keys(priceUpdates).length;
  if (Object.keys(priceUpdates).length > 0) {
    fs.writeFileSync(
      path.join(DATA_DIR, "products.json"),
      JSON.stringify(products, null, 2),
      "utf-8"
    );
    console.log(`\n📝 ${Object.keys(priceUpdates).length}件の価格を更新`);
  }

  // セール検知 → X投稿生成
  if (deals.length > 0) {
    console.log(`\n🎉 ${deals.length}件のセール商品を検知！`);
    await generateSalePosts(deals);
  } else {
    console.log("\n📊 セール商品はありませんでした");
  }
}

// --- セール検知 → X投稿生成 ---

async function generateSalePosts(deals) {
  const { google } = await import("googleapis");

  const credentials = JSON.parse(process.env.GOOGLE_CREDENTIALS || "{}");
  const auth = new google.auth.GoogleAuth({
    credentials,
    scopes: ["https://www.googleapis.com/auth/spreadsheets"],
  });
  const sheets = google.sheets({ version: "v4", auth });
  const spreadsheetId = process.env.X_SHEET_ID;

  if (!spreadsheetId) {
    console.log("⚠️ X_SHEET_ID 未設定。X投稿生成をスキップ");
    return;
  }

  const DRAFT_SHEET = "下書き管理";

  // 記事とのマッピング
  const articles = JSON.parse(
    fs.readFileSync(path.join(DATA_DIR, "articles.json"), "utf-8")
  );

  for (const deal of deals.slice(0, 3)) {
    // 1回の実行で最大3件
    const article = articles.find(
      (a) =>
        a.status === "published" && a.productIds.includes(deal.product.id)
    );

    const priceText = `¥${deal.currentPrice.toLocaleString()}`;
    const dropText = `${deal.dropPct}%OFF`;
    const articleUrl = article
      ? `https://camp-gear-lab.com/articles/${article.slug}`
      : "";

    // X投稿テキスト生成
    const text = article
      ? `🔥${deal.product.brand} ${deal.product.name.slice(0, 30)}が${dropText}！\n\n今なら${priceText}で手に入る。\n${deal.product.description.slice(0, 60)}\n\n詳しいレビューはこちら👇\n${articleUrl}\n\n#キャンプ #アウトドア #セール #Amazon`
      : `🔥${deal.product.brand} ${deal.product.name.slice(0, 30)}が${dropText}！\n\n今なら${priceText}で手に入る。\n${deal.product.description.slice(0, 80)}\n\n#キャンプ #アウトドア #セール #Amazon`;

    const id = `xp-sale-${Date.now()}-${Math.random().toString(36).slice(2, 6)}`;
    const now = new Date().toISOString();

    // Sheetsに下書き保存
    try {
      await sheets.spreadsheets.values.append({
        spreadsheetId,
        range: `${DRAFT_SHEET}!A:J`,
        valueInputOption: "RAW",
        requestBody: {
          values: [
            [
              id,
              "sale_alert",
              text,
              article?.slug || "",
              articleUrl,
              "#キャンプ #セール #Amazon",
              "draft",
              now.slice(0, 10),
              now,
              "",
            ],
          ],
        },
      });
      console.log(`  📝 X投稿下書き保存: ${deal.product.name.slice(0, 25)}`);
    } catch (err) {
      console.error(`  ❌ Sheets保存エラー: ${err.message}`);
    }
  }

  console.log(
    `\n✅ ${Math.min(deals.length, 3)}件のセール投稿を下書き保存しました`
  );
  console.log("  管理画面で確認・承認してください");
}

main()
  .then(async () => {
    // 価格更新を本番(Supabase)へ即反映（従来は週次パイプライン任せで最大1週間ラグ）
    if (process.argv.includes("--no-sync")) return;
    if (priceUpdateCount === 0) return; // 価格変更ゼロなら同期不要（無駄な全量upsertを回避）
    try {
      const { execSync } = await import("child_process").then((m) => m.default || m);
      console.log("\n[price-monitor] Supabaseへ商品を同期します...");
      const projectDir = path.join(path.dirname(new URL(import.meta.url).pathname), "..");
      execSync("node --dns-result-order=ipv4first scripts/sync-to-supabase.js", {
        stdio: "inherit",
        cwd: projectDir, // リポジトリ外から手動実行されてもスクリプトを見つけられるように
      });
    } catch (err) {
      console.error("[price-monitor] Supabase同期に失敗（価格は次回同期で反映されます）:", err.message);
    }
  })
  .catch((err) => {
    console.error("エラー:", err.message);
    process.exit(1);
  });
