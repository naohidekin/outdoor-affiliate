/**
 * Amazon PA-API v5 ラッパー
 * AWS Signature V4 の実装は scripts/price-monitor.js から移植
 */

import crypto from "crypto";

const HOST = "webservices.amazon.co.jp";
const REGION = "us-west-2";
const SERVICE = "ProductAdvertisingAPI";
const PARTNER_TAG = process.env.AMAZON_PARTNER_TAG || "camp78-22";

export interface AmazonItem {
  asin: string;
  title: string;
  brand: string;
  price: number | null;
  availability: "InStock" | "OutOfStock" | "Unknown";
  imageUrl: string;
  features: string[];
}

// --- AWS Signature V4 ---

function hmacSha256(key: string | Buffer, data: string): Buffer {
  return crypto.createHmac("sha256", key).update(data).digest();
}

function sha256(data: string): string {
  return crypto.createHash("sha256").update(data).digest("hex");
}

function getSignatureKey(key: string, dateStamp: string, region: string, service: string): Buffer {
  const kDate = hmacSha256("AWS4" + key, dateStamp);
  const kRegion = hmacSha256(kDate, region);
  const kService = hmacSha256(kRegion, service);
  return hmacSha256(kService, "aws4_request");
}

async function paApiRequest(operation: string, payload: object): Promise<unknown> {
  const accessKey = process.env.AMAZON_ACCESS_KEY;
  const secretKey = process.env.AMAZON_SECRET_KEY;
  if (!accessKey || !secretKey) {
    throw new Error("AMAZON_ACCESS_KEY / AMAZON_SECRET_KEY が未設定です");
  }

  const now = new Date();
  const amzDate = now.toISOString().replace(/[-:]/g, "").replace(/\.\d+Z$/, "Z");
  const dateStamp = amzDate.slice(0, 8);

  const apiPath = operation === "GetItems" ? "/paapi5/getitems"
    : operation === "SearchItems" ? "/paapi5/searchitems"
    : `/paapi5/${operation.toLowerCase()}`;

  const body = JSON.stringify(payload);
  const headers: Record<string, string> = {
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
    sha256(canonicalRequest),
  ].join("\n");

  const signingKey = getSignatureKey(secretKey, dateStamp, REGION, SERVICE);
  const signature = hmacSha256(signingKey, stringToSign).toString("hex");
  const authHeader = `AWS4-HMAC-SHA256 Credential=${accessKey}/${credentialScope}, SignedHeaders=${signedHeaders}, Signature=${signature}`;

  const res = await fetch(`https://${HOST}${apiPath}`, {
    method: "POST",
    headers: { ...headers, Authorization: authHeader },
    body,
  });

  if (!res.ok) {
    const text = await res.text();
    throw new Error(`PA-API error ${res.status}: ${text.slice(0, 300)}`);
  }

  return res.json();
}

// --- ASIN ユーティリティ ---

export function extractAsin(url: string): string | null {
  const match = url.match(/\/dp\/([A-Z0-9]{10})/);
  return match ? match[1] : null;
}

// --- レスポンス解析 ---

function parseItem(item: Record<string, unknown>): AmazonItem {
  const info = item.ItemInfo as Record<string, unknown> | undefined;
  const offers = item.Offers as Record<string, unknown> | undefined;
  const images = item.Images as Record<string, unknown> | undefined;

  const titleObj = (info?.Title as Record<string, unknown> | undefined);
  const title = (titleObj?.DisplayValue as string) || "";

  const byLineInfo = (info?.ByLineInfo as Record<string, unknown> | undefined);
  const contributors = (byLineInfo?.Brand as Record<string, unknown> | undefined);
  const brand = (contributors?.DisplayValue as string) || "";

  const listings = (offers?.Listings as Record<string, unknown>[] | undefined) || [];
  const listing = listings[0] as Record<string, unknown> | undefined;
  const priceObj = (listing?.Price as Record<string, unknown> | undefined);
  const price = priceObj ? (priceObj.Amount as number) : null;

  const availMsg = ((listing?.Availability as Record<string, unknown> | undefined)?.Message as string) || "";
  const availability: AmazonItem["availability"] =
    availMsg.includes("在庫あり") || availMsg.toLowerCase().includes("in stock")
      ? "InStock"
      : availMsg.includes("在庫なし") || availMsg.toLowerCase().includes("out of stock")
      ? "OutOfStock"
      : "Unknown";

  const primaryImg = (images?.Primary as Record<string, unknown> | undefined);
  const largeImg = (primaryImg?.Large as Record<string, unknown> | undefined);
  const imageUrl = (largeImg?.URL as string) || "";

  const featuresObj = (info?.Features as Record<string, unknown> | undefined);
  const features = (featuresObj?.DisplayValues as string[]) || [];

  return {
    asin: item.ASIN as string,
    title,
    brand,
    price,
    availability,
    imageUrl,
    features,
  };
}

const GETITEMS_RESOURCES = [
  "ItemInfo.Title",
  "ItemInfo.ByLineInfo",
  "ItemInfo.Features",
  "Offers.Listings.Price",
  "Offers.Listings.Availability.Message",
  "Images.Primary.Large",
];

// --- 公開API ---

/** 最大10件のASINから商品情報を取得 */
export async function getItemsByAsins(asins: string[]): Promise<AmazonItem[]> {
  if (asins.length === 0) return [];
  const data = await paApiRequest("GetItems", {
    ItemIds: asins.slice(0, 10),
    Resources: GETITEMS_RESOURCES,
    PartnerTag: PARTNER_TAG,
    PartnerType: "Associates",
    Marketplace: "www.amazon.co.jp",
  }) as Record<string, unknown>;
  const items = ((data.ItemsResult as Record<string, unknown>)?.Items as Record<string, unknown>[]) || [];
  return items.map(parseItem);
}

/** 全ASINを10件ずつバッチ処理（1秒間隔） */
export async function batchGetItems(asins: string[]): Promise<AmazonItem[]> {
  const results: AmazonItem[] = [];
  for (let i = 0; i < asins.length; i += 10) {
    const batch = asins.slice(i, i + 10);
    const items = await getItemsByAsins(batch);
    results.push(...items);
    if (i + 10 < asins.length) {
      await new Promise((r) => setTimeout(r, 1100));
    }
  }
  return results;
}

/** キーワードでAmazon商品を検索 */
export async function searchItems(keyword: string, browseNodeId?: string): Promise<AmazonItem[]> {
  const payload: Record<string, unknown> = {
    Keywords: keyword,
    Resources: GETITEMS_RESOURCES,
    PartnerTag: PARTNER_TAG,
    PartnerType: "Associates",
    Marketplace: "www.amazon.co.jp",
    ItemCount: 10,
  };
  if (browseNodeId) payload.BrowseNodeId = browseNodeId;

  const data = await paApiRequest("SearchItems", payload) as Record<string, unknown>;
  const items = ((data.SearchResult as Record<string, unknown>)?.Items as Record<string, unknown>[]) || [];
  return items.map(parseItem);
}
