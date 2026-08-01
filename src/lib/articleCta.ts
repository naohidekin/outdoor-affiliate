// 記事タイプ別のCTA出し分け。
//
// 方針（2026-08-01 外部レビュー反映）:
// - 安全・医学・知識系の記事は、本文より前に商品購入ボタンを出さない。
//   「現役小児科医監修」を掲げるサイトで、救急・熱中症などの記事の冒頭に
//   いきなり販売ボタンが並ぶと信頼を損なう。末尾CTA（読了後）は残す。
// - それ以外（ランキング・比較・レビュー・ギアガイド）は従来通り冒頭+末尾。
//   スラッグや見出しからの自動分類は誤爆する（エース記事の
//   portable-cooler-fan-guide が「ガイド」判定になる等）ため、
//   明示リストで管理する。追加はこのセットに1行足すだけ。
const NO_TOP_CTA_SLUGS = new Set<string>([
  "family-camp-safety-guide", // 子連れキャンプ安全ガイド（安全知識のハブ）
  "kids-camp-first-aid-kit", // 救急セット（医学系）
  "kids-camp-heatstroke-prevention", // 熱中症予防（医学系）
]);

// 冒頭の商品CTA（RecommendationCTA）と楽天買い時バナーを出すか。
// PR表記（AffiliateDisclosure）はこの判定に関わらず、本文中に
// アフィリエイトリンクがある限り必ず表示する（ステマ規制対応）
export function showTopCta(slug: string): boolean {
  return !NO_TOP_CTA_SLUGS.has(slug);
}
