export type HeroType = "tile" | "split" | "photo";

/**
 * slugから記事タイプを判定する
 * tile: ランキング・おすすめ系（30件）
 * split: A vs B 比較系（5件）
 * photo: ガイド・チェックリスト系（18件）
 */
export function getHeroType(slug: string): HeroType {
  if (/ranking|budget/.test(slug)) return "tile";
  if (/-vs-|-showdown-|-comparison-|-alternatives/.test(slug)) return "split";
  return "photo";
}
