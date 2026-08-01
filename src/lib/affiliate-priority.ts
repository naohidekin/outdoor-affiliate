import { Product } from "./types";

// 楽天アフィリエイトは1商品1個につき報酬上限1,000円（料率アップショップを除く）。
// 2026年7月の成果レポートで実測確認: 売上¥82,665のテントでも報酬¥1,000
// （スポーツ・アウトドア4%なら¥3,306のはずが上限で頭打ち）。
// 一方Amazonは上限なしで実効料率3.67%（7月実績: 売上¥187,210→紹介料¥6,864）。
// 損益分岐は「Amazon 3% × 価格 > 楽天上限¥1,000」となる約¥33,000。
// それ以上の高単価商品はAmazon（2024-08-07に1,000円上限を廃止）を主導線にする。
export const AMAZON_PRIMARY_PRICE = 33000;

export function isAmazonPrimary(product: Product): boolean {
  return !!product.amazonUrl && product.price >= AMAZON_PRIMARY_PRICE;
}
