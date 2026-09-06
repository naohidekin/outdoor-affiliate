import type { Product } from "./types.ts";

export type TrackingProduct = Pick<Product, "id" | "name" | "affiliateUrl" | "amazonUrl" | "yahooUrl">;
export type AffiliateProduct = { id: string; name: string };

function parseUrl(href: string): URL | null {
  try {
    const url = new URL(href);
    return /^(https?:)$/.test(url.protocol) && !url.username && !url.password ? url : null;
  } catch { return null; }
}

const hostIs = (host: string, domain: string) => host === domain || host.endsWith(`.${domain}`);

/** Product destinations only. Search pages, ROOM collections and opaque short links are not products. */
export function affiliateProductKey(href: string): string | null {
  let url = parseUrl(href);
  if (!url) return null;
  // Unwrap only known redirectors. Never recognize a merchant URL embedded in an unrelated site's query.
  if (hostIs(url.hostname, "hb.afl.rakuten.co.jp")) {
    url = parseUrl(url.searchParams.get("pc") || url.searchParams.get("m") || "");
    if (!url || !["item.rakuten.co.jp", "m.rakuten.co.jp", "product.rakuten.co.jp"].includes(url.hostname)) return null;
  } else if (hostIs(url.hostname, "ck.jp.ap.valuecommerce.com")) {
    url = parseUrl(url.searchParams.get("vc_url") || "");
    if (!url || !hostIs(url.hostname, "shopping.yahoo.co.jp")) return null;
  }
  let key: string | null = null;
  if (hostIs(url.hostname, "amazon.co.jp")) {
    const match = url.pathname.match(/\/(?:dp|gp\/product)\/([a-z0-9]{10})(?:\/|$)/i);
    if (match) key = `amazon:${match[1].toUpperCase()}`;
  } else if (url.hostname === "item.rakuten.co.jp") {
    const match = url.pathname.match(/^\/([a-z0-9_-]+)\/([a-z0-9_.-]+)\/?$/i);
    if (match) key = `rakuten:${match[1]}/${match[2]}`;
  } else if (url.hostname === "product.rakuten.co.jp") {
    const match = url.pathname.match(/^\/product\/-\/([a-z0-9]+)\/?$/i);
    if (match) key = `rakuten-catalog:${match[1]}`;
  } else if (url.hostname === "store.shopping.yahoo.co.jp") {
    const match = url.pathname.match(/^\/([a-z0-9_-]+)\/([a-z0-9_.-]+)\.html$/i);
    if (match) key = `yahoo:${match[1]}/${match[2]}`;
  }
  // Keep IDs within both our click endpoint's and GA4 custom parameter limits.
  return key && key.length <= 100 ? key : null;
}

function lookupKey(href: string): string | null {
  const key = affiliateProductKey(href);
  if (key) return key;
  const url = parseUrl(href);
  // An opaque link can match an exact catalogue URL, but cannot identify a new product by itself.
  if (url && ["amzn.to", "amzn.asia", "a.r10.to"].includes(url.hostname)) {
    return `short:${url.hostname}${url.pathname}`;
  }
  return null;
}

export function buildAffiliateProductIndex(products: TrackingProduct[]) {
  const index = new Map<string, AffiliateProduct | null>();
  for (const product of products) {
    for (const href of [product.affiliateUrl, product.amazonUrl, product.yahooUrl]) {
      const key = href ? lookupKey(href) : null;
      if (!key) continue;
      const existing = index.get(key);
      // Duplicate destinations must not silently attribute clicks to the first registered product.
      if (index.has(key) && existing?.id !== product.id) index.set(key, null);
      else if (!index.has(key)) index.set(key, { id: product.id, name: product.name });
    }
  }
  return index;
}

export function resolveAffiliateProduct(href: string, index: Map<string, AffiliateProduct | null>): AffiliateProduct {
  const key = lookupKey(href);
  const hit = key ? index.get(key) : null;
  if (hit) return hit;
  // Unregistered products remain distinguishable by their destination. Do not invent a product name.
  return { id: affiliateProductKey(href) || "inline", name: "" };
}

export function isInternalArticleLink(href?: string): boolean {
  if (!href || href.startsWith("#") || /^\/(?!\/)/.test(href)) return true;
  const url = parseUrl(href.startsWith("//") ? `https:${href}` : href);
  return !!url && url.hostname === "camp-gear-lab.com";
}
