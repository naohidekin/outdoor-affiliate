import type { Product } from "./types.ts";
import type { AffiliateStore } from "./trackAffiliateClick.ts";
import { isAmazonPrimary } from "./affiliate-priority.ts";

export function getProductMerchants(product: Product) {
  const candidates: { store: AffiliateStore; label: string; href: string }[] = [
    { store: "rakuten", label: "楽天市場", href: product.affiliateUrl },
    { store: "amazon", label: "Amazon", href: product.amazonUrl },
    { store: "yahoo", label: "Yahoo!ショッピング", href: product.yahooUrl ?? "" },
  ];
  if (isAmazonPrimary(product)) [candidates[0], candidates[1]] = [candidates[1], candidates[0]];
  return candidates.filter(({ href }) => {
    try { const url = new URL(href); return url.protocol === "https:" && !url.username && !url.password; }
    catch { return false; }
  }).map((merchant, index) => ({ ...merchant, rank: index + 1 }));
}
