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
 *   node scripts/price-monitor.js --dry-run        # 書き込み・同期なし（推奨: まずこれ）
 *   node scripts/price-monitor.js
 *   node scripts/price-monitor.js --threshold=15   # 15%以上の値下げのみ通知
 *   node scripts/price-monitor.js --no-sync        # 書き込むがSupabase同期はしない
 *   node scripts/price-monitor.js --guard-max=3.0  # 変動率ガードを緩める
 *
 * 変動率ガード: 前回価格の 0.5〜2.0倍を外れる更新は自動適用せず
 * data/price-held-back.json に保留する。誤ったASIN（本体ではなくパーツ）を
 * 指していると異常な価格を掴むため。目視後 apply-held-price.mjs で適用する。
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

// 書き込み・Supabase同期・ISR再検証をすべて止める
const DRY_RUN = process.argv.includes("--dry-run");

// 変動率ガード。この範囲を外れた更新は自動適用せず保留する
const numArg = (name, fallback) =>
  parseFloat(process.argv.find((a) => a.startsWith(`${name}=`))?.split("=")[1] || fallback);
const GUARD_MIN = numArg("--guard-min", "0.5");
const GUARD_MAX = numArg("--guard-max", "2.0");

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
  const heldBack = [];

  // 10件ずつバッチ処理（PA-API制限）
  for (let i = 0; i < productAsins.length; i += 10) {
    const batch = productAsins.slice(i, i + 10);
    const asins = batch.map((p) => p.asin);

    try {
      const items = await getItemPrices(asins);

      for (const item of items) {
        const asin = item.ASIN;
        // 同じASINが複数商品に登録されているケースがある（焚火台L・おにやんま君など）。
        // find だと片方しか更新されず、重複間で価格が食い違う
        const matched = batch.filter((p) => p.asin === asin);
        const product = matched[0];
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

        // 変動が大きすぎる場合は自動適用せず保留する。
        // 2026-08-05: 誤ったASIN（本体ではなくパーツ）を参照していた商品で
        // 焚火台Lが¥18,600→¥1,845になり、そのまま本番へ出た。
        // 正しい値上がりも混じるため、破棄せずレポートして目視に回す。
        const ratio = prevPrice > 0 ? currentPrice / prevPrice : 1;
        if (ratio < GUARD_MIN || ratio > GUARD_MAX) {
          heldBack.push({
            ids: matched.map((m) => m.id),
            name: product.name,
            asin,
            prevPrice,
            currentPrice,
            ratio,
            amazonUrl: product.amazonUrl,
          });
          console.log(
            `  ⏸  保留 ${product.name.slice(0, 28)} ¥${prevPrice.toLocaleString()} → ¥${currentPrice.toLocaleString()} (${Math.round(ratio * 100)}%)`
          );
          // 履歴も更新しない。次回も同じ差分として検出させる
          delete priceUpdates[asin];
          continue;
        }

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
        // 必ず原本(products配列)側を更新する（コピーだけ更新すると書き出しに反映されない）。
        // 同じASINの商品が複数あるときは全部そろえる
        for (const m of matched) {
          const original = products.find((p) => p.id === m.id);
          if (!original) continue;
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

  // 保留分の報告。破棄せず一覧に出して目視に回す
  if (heldBack.length > 0) {
    console.log(
      `\n⏸  ガードで保留: ${heldBack.length}件（変動が ${Math.round(GUARD_MIN * 100)}〜${Math.round(GUARD_MAX * 100)}% の外）`
    );
    console.log("   誤ったASIN（本体でなくパーツ等）を指している可能性があります。");
    console.log("   URLを開いて確認し、正しければ下のコマンドで個別に適用してください。\n");
    for (const h of heldBack) {
      console.log(
        `   ${String(Math.round(h.ratio * 100)).padStart(4)}%  ¥${String(h.prevPrice).padStart(7)} → ¥${String(h.currentPrice).padStart(7)}  ${h.name.slice(0, 30)}`
      );
      console.log(`         ${h.ids.join(", ")}  ${h.amazonUrl}`);
    }
    const heldPath = path.join(DATA_DIR, "price-held-back.json");
    if (!DRY_RUN) {
      fs.writeFileSync(
        heldPath,
        JSON.stringify({ checkedAt: new Date().toISOString(), items: heldBack }, null, 2),
        "utf-8"
      );
      console.log(`\n   一覧: ${heldPath}`);
    }
    console.log(
      `   適用する場合: node scripts/apply-held-price.mjs <商品ID> [<商品ID>...]`
    );
  }

  if (DRY_RUN) {
    console.log(
      `\n🔍 DRY RUN: 書き込みなし（更新対象 ${Object.keys(priceUpdates).length}件 / 保留 ${heldBack.length}件 / セール検知 ${deals.length}件）`
    );
    return;
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
    if (DRY_RUN) return; // dry-run は同期・ISR再検証まで含めて何もしない
    if (process.argv.includes("--no-sync")) return;
    if (priceUpdateCount === 0) return; // 価格変更ゼロなら同期不要（無駄な全量upsertを回避）
    try {
      const { execSync } = await import("child_process").then((m) => m.default || m);
      console.log("\n[price-monitor] Supabaseへ商品を同期します...");
      const projectDir = path.join(path.dirname(new URL(import.meta.url).pathname), "..");
      // --no-pull: auto-pull(Supabase→local) が走ると、まだDBに無い
      // ローカルの更新が旧値で上書きされうる（2026-08-05に差し戻しが消えた）
      execSync("node --dns-result-order=ipv4first scripts/sync-to-supabase.js --no-pull", {
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
