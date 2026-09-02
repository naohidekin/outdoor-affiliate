// @ts-nocheck
/**
 * Product Lookup 共通モジュール
 *
 * 商品名で楽天APIを検索し、products.jsonに自動追加する共通パイプ。
 * viral-scout, youtube-researcher, rakuten-ranking 等から利用。
 *
 * Usage (ESM):
 *   import { lookupAndRegisterProducts } from "./product-lookup.mjs";
 *   const results = await lookupAndRegisterProducts([
 *     { name: "NANGA オーロラ600DX", brand: "NANGA", axis: "camp" }
 *   ]);
 */

import fs from "fs";
import path from "path";
import { fileURLToPath } from "url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const DATA_DIR = path.join(__dirname, "..", "..", "data");
const PRODUCTS_FILE = path.join(DATA_DIR, "products.json");

const RAKUTEN_API_URL = "https://openapi.rakuten.co.jp/ichibams/api/IchibaItem/Search/20260701";
const RAKUTEN_AFFILIATE_ID = process.env.RAKUTEN_AFFILIATE_ID || "18eb3228.621d8df3.18eb3229.ec5f8d49";

// === 楽天API検索 ===

async function searchRakuten(keyword, hits = 5) {
  const appId = process.env.RAKUTEN_APP_ID;
  const accessKey = process.env.RAKUTEN_ACCESS_KEY;
  if (!appId) {
    console.warn("[product-lookup] RAKUTEN_APP_ID 未設定");
    return [];
  }

  const params = new URLSearchParams({
    applicationId: appId,
    ...(accessKey ? { accessKey } : {}),
    affiliateId: RAKUTEN_AFFILIATE_ID,
    keyword,
    hits: String(hits),
    sort: "-reviewAverage",
    imageFlag: "1",
    formatVersion: "2",
  });

  try {
    const res = await fetch(`${RAKUTEN_API_URL}?${params}`);
    if (!res.ok) {
      console.warn(`[product-lookup] 楽天API ${res.status}: ${keyword}`);
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
    }));
  } catch (err) {
    console.warn(`[product-lookup] 楽天検索エラー: ${err.message}`);
    return [];
  }
}

// === 重複チェック ===

function normalize(s) {
  return (s || "").replace(/[\s\-・　]/g, "").toLowerCase().slice(0, 60);
}

function isDuplicate(productsData, name) {
  const norm = normalize(name);
  return productsData.some(
    (x) => x.name === name.slice(0, 80) || normalize(x.name) === norm
  );
}

// === products.json 読み書き ===

function loadProducts() {
  try {
    const raw = JSON.parse(fs.readFileSync(PRODUCTS_FILE, "utf-8"));
    return Array.isArray(raw) ? raw : raw.products || [];
  } catch {
    return [];
  }
}

function saveProducts(products) {
  fs.writeFileSync(PRODUCTS_FILE, JSON.stringify(products, null, 2) + "\n", "utf-8");
}

// === メイン: 商品名リストから楽天検索して登録 ===

/**
 * @param {Array<{ name: string, brand?: string, axis?: string, category?: string }>} candidates
 * @param {{ dryRun?: boolean, source?: string }} opts
 * @returns {Promise<{ added: number, skipped: number, notFound: number, products: Array }>}
 */
export async function lookupAndRegisterProducts(candidates, opts = {}) {
  const { dryRun = false, source = "product-lookup" } = opts;
  const productsData = loadProducts();
  const today = new Date().toISOString().slice(0, 10);

  let added = 0;
  let skipped = 0;
  let notFound = 0;
  const addedProducts = [];

  for (const candidate of candidates) {
    if (!candidate.name) continue;

    // 重複チェック
    if (isDuplicate(productsData, candidate.name)) {
      skipped++;
      continue;
    }

    // 楽天検索
    const results = await searchRakuten(candidate.name, 3);
    // 待機はリクエスト直後に置く。ループ末尾に置いていたため、
    // 「0件だった」「正式名で重複だった」で continue すると
    // 待たずに次のリクエストへ行っていた（2026-08-23 発覚）。
    // 楽天の規定は1つのapplication_idにつき1秒に1回以下
    await new Promise((r) => setTimeout(r, 1200));
    if (results.length === 0) {
      notFound++;
      continue;
    }

    // ベストマッチ（レビュー平均が高いもの）を採用
    const best = results[0];
    const productId = `${source}-${Date.now()}-${Math.random().toString(36).slice(2, 6)}`;

    // 再度重複チェック（楽天の正式名で）
    if (isDuplicate(productsData, best.itemName)) {
      skipped++;
      continue;
    }

    const product = {
      id: productId,
      name: best.itemName.slice(0, 100),
      brand: candidate.brand || "",
      price: best.itemPrice || 0,
      imageUrl: best.imageUrl || "",
      affiliateUrl: best.affiliateUrl || "",
      amazonUrl: "",
      categoryId: candidate.category || "",
      specs: {},
      description: "",
      rating: best.reviewAverage || 0,
      autoAdded: true,
      addedBy: source,
      addedAt: today,
      axis: candidate.axis || "camp",
    };

    if (!dryRun) {
      productsData.push(product);
    }
    addedProducts.push(product);
    added++;

    console.log(`[product-lookup] + ${best.itemName.slice(0, 50)} (¥${best.itemPrice}) [${candidate.axis || "camp"}]`);
  }

  if (!dryRun && added > 0) {
    saveProducts(productsData);
    console.log(`[product-lookup] products.json に ${added}件追加`);
  }

  return { added, skipped, notFound, products: addedProducts };
}

export { searchRakuten, isDuplicate, loadProducts, normalize };
