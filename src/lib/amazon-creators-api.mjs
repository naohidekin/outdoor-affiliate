/**
 * Amazon Creators API クライアント（共通モジュール）
 *
 * PA-API v5 は 2026-05-15 に廃止。後継の Creators API は OAuth 2.0
 * (client_credentials) でトークンを取り、Bearer で叩く。
 *
 * 認証情報はアソシエイト・セントラル → クリエイターAPI で発行した
 * 「認証情報ID」(amzn1.application-oa2-client....) と Secret。
 *
 * 環境変数（旧 PA-API の変数名に入れてあっても読む）:
 *   AMAZON_CREDENTIAL_ID      / AMAZON_ACCESS_KEY
 *   AMAZON_CREDENTIAL_SECRET  / AMAZON_SECRET_KEY
 *   AMAZON_CREDENTIAL_VERSION … 既定 "3.3"（日本）
 *   AMAZON_PARTNER_TAG        … 既定 "camp78-22"
 *
 * 既存の fetch-product-images.mjs / link-fix.mjs / refetch-candidates.mjs は
 * それぞれ同等の実装を内包している。動作中のため今回は手を入れていない。
 * 新規・改修分はこのモジュールを使う。
 */

const TOKEN_ENDPOINTS = {
  "3.1": "https://api.amazon.com/auth/o2/token",
  "3.2": "https://api.amazon.co.uk/auth/o2/token",
  "3.3": "https://api.amazon.co.jp/auth/o2/token",
};
const API_BASE = "https://creatorsapi.amazon";
const MARKETPLACE = "www.amazon.co.jp";

export function credentials() {
  return {
    id: process.env.AMAZON_CREDENTIAL_ID || process.env.AMAZON_ACCESS_KEY,
    secret: process.env.AMAZON_CREDENTIAL_SECRET || process.env.AMAZON_SECRET_KEY,
    version: process.env.AMAZON_CREDENTIAL_VERSION || "3.3",
    partnerTag: process.env.AMAZON_PARTNER_TAG || "camp78-22",
  };
}

export function hasCredentials() {
  const c = credentials();
  return Boolean(c.id && c.secret);
}

let cachedToken = null;

export async function getAccessToken() {
  if (cachedToken && Date.now() < cachedToken.expiresAt) return cachedToken.token;
  const c = credentials();
  if (!c.id || !c.secret) {
    throw new Error(
      "Creators API認証情報がありません（.env.local の AMAZON_CREDENTIAL_ID / AMAZON_CREDENTIAL_SECRET）"
    );
  }
  const endpoint = TOKEN_ENDPOINTS[c.version] || TOKEN_ENDPOINTS["3.3"];
  const res = await fetch(endpoint, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      grant_type: "client_credentials",
      client_id: c.id,
      client_secret: c.secret,
      scope: "creatorsapi::default",
    }),
  });
  if (!res.ok) {
    throw new Error(`トークン取得失敗 ${res.status}: ${(await res.text()).slice(0, 200)}`);
  }
  const data = await res.json();
  cachedToken = {
    token: data.access_token,
    expiresAt: Date.now() + (Number(data.expires_in || 3600) - 60) * 1000,
  };
  return cachedToken.token;
}

/** 429 は指数バックオフで再試行する */
export async function creatorsApi(apiPath, payload) {
  const waits = [3000, 8000, 20000];
  for (let attempt = 0; ; attempt++) {
    const token = await getAccessToken();
    const res = await fetch(`${API_BASE}${apiPath}`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        Authorization: `Bearer ${token}`,
        "x-marketplace": MARKETPLACE,
      },
      body: JSON.stringify(payload),
    });
    const text = await res.text();
    if (res.status === 429 && attempt < waits.length) {
      const wait = waits[attempt];
      console.log(`  ⏳ レート制限(429) — ${wait / 1000}秒待機して再試行 (${attempt + 1}/${waits.length})`);
      await new Promise((r) => setTimeout(r, wait));
      continue;
    }
    if (!res.ok) throw new Error(`Creators API ${res.status}: ${text.slice(0, 300)}`);
    return JSON.parse(text);
  }
}

export const DEFAULT_RESOURCES = [
  "itemInfo.title",
  "images.primary.large",
  "offersV2.listings.price",
];

/**
 * ASIN から商品情報を取得する。getItems は1回10件まで。
 * バッチ間は待機を挟む（既定3秒）。
 */
export async function getItems(asins, { resources = DEFAULT_RESOURCES, batchDelayMs = 3000 } = {}) {
  const c = credentials();
  const items = [];
  const errors = [];
  for (let i = 0; i < asins.length; i += 10) {
    const batch = asins.slice(i, i + 10);
    const data = await creatorsApi("/catalog/v1/getItems", {
      itemIds: batch,
      partnerTag: c.partnerTag,
      resources,
    });
    items.push(...(data.itemsResult?.items || []));
    errors.push(...(data.errors || []));
    if (i + 10 < asins.length) await new Promise((r) => setTimeout(r, batchDelayMs));
  }
  return { items, errors };
}

export async function searchItems(keywords, { resources = DEFAULT_RESOURCES, itemCount = 10 } = {}) {
  const c = credentials();
  const data = await creatorsApi("/catalog/v1/searchItems", {
    keywords,
    partnerTag: c.partnerTag,
    resources,
    itemCount,
  });
  return data.searchResult?.items || [];
}

/** ASIN を /dp/ 形式のURLから取り出す */
export function asinOf(url) {
  const m = (url || "").match(/\/(?:dp|gp\/product)\/([A-Z0-9]{10})/i);
  return m ? m[1].toUpperCase() : null;
}

/** offersV2 から税込価格を取り出す。取得できなければ null */
export function priceOf(item) {
  const amount = item?.offersV2?.listings?.[0]?.price?.money?.amount;
  return typeof amount === "number" ? Math.round(amount) : null;
}

export function titleOf(item) {
  return item?.itemInfo?.title?.displayValue || "";
}
