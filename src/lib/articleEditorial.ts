import type { Article, Product } from "./types.ts";

export interface EditorialPick {
  productId: string;
  audience: string;
  reason: string;
  caution: string;
  evidence: "限定版を使用" | "仕様比較";
}

// Article-specific decisions live here, independently of the database's product order.
// Evidence labels describe the basis of this pick; they are not a medical endorsement.
export const EDITORIAL_PICKS: Record<string, EditorialPick[]> = {
  "landlock-vs-landnest-shelter": [
    { productId: "tent-f06", audience: "設営の扱いやすさを重視する家族に", reason: "運営者がBlack Frame Editionを買い替え先に選んだシリーズ。設営・撤収の負担を抑えたい方の候補です。", caution: "掲載商品は通常版です。使用した限定版とは付属品が異なります。寝室の奥行きも確認を。", evidence: "限定版を使用" },
    { productId: "tent-f03", audience: "寝室とリビングの広さを重視する方に", reason: "家族の寝具と荷物を配置できるか、ランドネストと寸法を比べて選ぶ候補です。", caution: "幕体の重さと、張り綱を含む設営スペースを確認してください。", evidence: "仕様比較" },
    { productId: "tent-f-landlock-x", audience: "新しい構造・装備まで比較したい方に", reason: "従来のランドロックと装備・仕様の違いを確認し、予算に見合うか検討するモデルです。", caution: "必要なペグやオプションを含めた総額で比較してください。", evidence: "仕様比較" },
  ],
};

export function getEditorialPicks(slug: string, products: Product[]) {
  const byId = new Map(products.map((p) => [p.id, p]));
  return (EDITORIAL_PICKS[slug] ?? []).flatMap((pick) => {
    const product = byId.get(pick.productId);
    return product ? [{ product, ...pick }] : [];
  });
}

/** Hero comparisons must not silently turn ancillary products into competitors. */
export function getPrimaryProducts(article: Pick<Article, "slug" | "categoryId">, products: Product[]) {
  const picks = getEditorialPicks(article.slug, products);
  if (picks.length) return picks.map((p) => p.product);
  // This drink bottle is stored under "cooler" in the existing data. It remains
  // available to the article body, but is not a competing cooler-box model.
  const excluded = article.slug === "cooler-box-brand-comparison-2026" ? ["growler-002"] : [];
  return products.filter((p) => p.categoryId === article.categoryId && !excluded.includes(p.id));
}

const FIELD_REVIEWS = new Set([
  "snow-peak-amenity-dome-l-10year-review",
]);
export function getArticleLabel(article: Pick<Article, "slug" | "title">) {
  if (FIELD_REVIEWS.has(article.slug)) return "長期使用レビュー";
  if (/safety|first-aid|heatstroke/.test(article.slug)) return "安全ガイド";
  if (/-vs-|-comparison|比較/.test(article.slug + article.title)) return "比較・選び方";
  if (/ranking|おすすめ/.test(article.slug + article.title)) return "用途別のおすすめ";
  return "ギアガイド";
}

export const FEATURED_SLUGS = [
  "landlock-vs-landnest-shelter",
  "family-tent-ranking",
  "portable-cooler-fan-guide",
] as const;

export function getSeasonalFeature(month: number) {
  if (month >= 6 && month <= 8) return { label: "夏のキャンプ支度", description: "暑さ・虫対策と、夜を過ごす装備を確認。", slugs: ["portable-cooler-fan-guide", "summer-camp-heat-gear-guide", "camp-insect-repellent-guide"] };
  if (month >= 9 && month <= 11) return { label: "秋のキャンプ支度", description: "夜の冷えに備えて、寝具と持ち物を見直す。", slugs: ["kids-sleeping-bag-ranking", "nanga-sleeping-bag-comparison", "winter-camp-beginners-checklist"] };
  if (month === 12 || month <= 2) return { label: "冬のキャンプ支度", description: "防寒装備と、暖房器具の使い方を確認。", slugs: ["winter-camp-beginners-checklist", "winter-camp-heating-comparison", "kids-sleeping-bag-ranking"] };
  return { label: "春のキャンプ支度", description: "家族のテントと寝具を、次のお出かけに合わせて選ぶ。", slugs: ["family-tent-ranking", "kids-sleeping-bag-ranking", "family-camp-safety-guide"] };
}
