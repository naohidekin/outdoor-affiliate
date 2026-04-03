#!/usr/bin/env node

/**
 * Amazon 価格監視 & セール検知スクリプト
 * PA-API v5 で商品価格を取得し、値下げ・セールを検知
 * → 検知時に X投稿を自動生成してGoogle Sheetsに保存
 *
 * 必要な環境変数:
 *   AMAZON_ACCESS_KEY   — PA-API アクセスキー
 *   AMAZON_SECRET_KEY   — PA-API シークレットキー
 *   AMAZON_PARTNER_TAG  — アソシエイトタグ (例: nao78-22)
 *
 * 使い方:
 *   node scripts/price-monitor.js
 *   node scripts/price-monitor.js --threshold=15  (15%以上の値下げのみ通知)
 */

import fs from "fs";
import path from "path";
import crypto from "crypto";
import { fileURLToPath } from "url";

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

const ACCESS_KEY = process.env.AMAZON_ACCESS_KEY;
const SECRET_KEY = process.env.AMAZON_SECRET_KEY;
const PARTNER_TAG = process.env.AMAZON_PARTNER_TAG || "nao78-22";
const THRESHOLD = parseInt(
  process.argv.find((a) => a.startsWith("--threshold="))?.split("=")[1] || "10"
);

const HOST = "webservices.amazon.co.jp";
const REGION = "us-west-2";
const SERVICE = "ProductAdvertisingAPI";

// --- PA-API v5 AWS Signature V4 ---

function hmacSha256(key, data) {
  return crypto.createHmac("sha256", key).update(data).digest();
}

function sha256(data) {
  return crypto.createHash("sha256").update(data).digest("hex");
}

function getSignatureKey(key, dateStamp, region, service) {
  const kDate = hmacSha256("AWS4" + key, dateStamp);
  const kRegion = hmacSha256(kDate, region);
  const kService = hmacSha256(kRegion, service);
  return hmacSha256(kService, "aws4_request");
}

async function paApiRequest(operation, payload) {
  const now = new Date();
  const amzDate = now.toISOString().replace(/[-:]/g, "").replace(/\.\d+Z$/, "Z");
  const dateStamp = amzDate.slice(0, 8);

  const body = JSON.stringify(payload);
  const headers = {
    "content-encoding": "amz-1.0",
    "content-type": "application/json; charset=utf-8",
    host: HOST,
    "x-amz-date": amzDate,
    "x-amz-target": `com.amazon.paapi5.v1.ProductAdvertisingAPIv1.${operation}`,
  };

  const signedHeaders = Object.keys(headers).sort().join(";");
  const canonicalHeaders = Object.keys(headers)
    .sort()
    .map((k) => `${k}:${headers[k]}`)
    .join("\n");

  const canonicalRequest = [
    "POST",
    "/paapi5/" + operation.toLowerCase().replace(/([A-Z])/g, (m) => m).replace(/([a-z])([A-Z])/g, "$1-$2").toLowerCase().replace("get-", "get"),
    "",
    canonicalHeaders + "\n",
    signedHeaders,
    sha256(body),
  ].join("\n");

  // Fix path for PA-API
  const apiPath = `/paapi5/${operation === "GetItems" ? "getitems" : operation === "SearchItems" ? "searchitems" : operation.toLowerCase()}`;
  const canonicalRequestFixed = [
    "POST",
    apiPath,
    "",
    canonicalHeaders + "\n",
    signedHeaders,
    sha256(body),
  ].join("\n");

  const credentialScope = `${dateStamp}/${REGION}/${SERVICE}/aws4_request`;
  const stringToSign = [
    "AWS4-HMAC-SHA256",
    amzDate,
    credentialScope,
    sha256(canonicalRequestFixed),
  ].join("\n");

  const signingKey = getSignatureKey(SECRET_KEY, dateStamp, REGION, SERVICE);
  const signature = hmacSha256(signingKey, stringToSign).toString("hex");

  const authHeader = `AWS4-HMAC-SHA256 Credential=${ACCESS_KEY}/${credentialScope}, SignedHeaders=${signedHeaders}, Signature=${signature}`;

  const res = await fetch(`https://${HOST}${apiPath}`, {
    method: "POST",
    headers: { ...headers, Authorization: authHeader },
    body,
  });

  if (!res.ok) {
    const text = await res.text();
    throw new Error(`PA-API error ${res.status}: ${text.slice(0, 200)}`);
  }

  return res.json();
}

// --- 価格取得 ---

function extractAsin(url) {
  const match = url.match(/\/dp\/([A-Z0-9]{10})/);
  return match ? match[1] : null;
}

async function getItemPrices(asins) {
  // PA-API GetItems は最大10件
  const payload = {
    ItemIds: asins,
    Resources: [
      "ItemInfo.Title",
      "Offers.Listings.Price",
      "Offers.Listings.SavingBasis",
      "Offers.Listings.MerchantInfo",
      "Offers.Listings.Promotions",
    ],
    PartnerTag: PARTNER_TAG,
    PartnerType: "Associates",
    Marketplace: "www.amazon.co.jp",
  };

  const data = await paApiRequest("GetItems", payload);
  return data.ItemsResult?.Items || [];
}

// --- メイン処理 ---

async function main() {
  if (!ACCESS_KEY || !SECRET_KEY) {
    console.log("⚠️ PA-API認証情報が未設定です。");
    console.log("");
    console.log("以下を .env.local に追加してください:");
    console.log("  AMAZON_ACCESS_KEY=your_access_key");
    console.log("  AMAZON_SECRET_KEY=your_secret_key");
    console.log("  AMAZON_PARTNER_TAG=nao78-22");
    console.log("");
    console.log("PA-APIのアクセスキーの取得方法:");
    console.log("  1. https://affiliate.amazon.co.jp/ にログイン");
    console.log("  2. ツール → Product Advertising API");
    console.log("  3. 認証情報を管理 → アクセスキーを生成");
    console.log("");
    console.log("※ PA-APIを利用するには、直近30日間に3件以上の売上実績が必要です");
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

        // products.json の価格も更新
        product.price = currentPrice;
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

main().catch((err) => {
  console.error("エラー:", err.message);
  process.exit(1);
});
