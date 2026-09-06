import type { Product } from "./types.ts";

// Retain the existing merchant order while gathering comparable observations.
// This price threshold is a display heuristic, not a demonstrated revenue optimum.
// Evaluate by page, product and placement using matching reporting periods;
// account-wide sales can include unrelated purchases and other traffic sources.
export const AMAZON_PRIMARY_PRICE = 33000;

export function isAmazonPrimary(product: Product): boolean {
  return !!product.amazonUrl && product.price >= AMAZON_PRIMARY_PRICE;
}
