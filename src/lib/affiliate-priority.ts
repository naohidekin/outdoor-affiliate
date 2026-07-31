import { Product } from "./types";

// 楽天アフィリエイトは1商品1個につき報酬上限1,000円（料率アップショップを除く）。
// 実効料率2〜4%だと5万円前後で上限に到達するため、それ以上の高単価商品は
// 上限のないAmazon（2024-08-07に1,000円上限を廃止）を主導線にする。
export const AMAZON_PRIMARY_PRICE = 50000;

export function isAmazonPrimary(product: Product): boolean {
  return !!product.amazonUrl && product.price >= AMAZON_PRIMARY_PRICE;
}
