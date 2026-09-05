import type { Article } from "./types.ts";

type ArticleSummary = Pick<Article, "id" | "slug" | "title" | "categoryId" | "productIds" | "status" | "tags" | "publishedAt">;
export interface NextRead { article: ArticleSummary; reason: string }

// 検索意図を補完する順序。リンク先が下書き・削除済みなら通常の選定に戻る。
export const NEXT_READS: Record<string, { slug: string; reason: string }[]> = {
  "landlock-vs-landnest-shelter": [
    { slug: "snow-peak-amenity-dome-l-10year-review", reason: "長く使った記録を読む" },
    { slug: "snow-peak-landlock-x-review", reason: "新型の仕様を詳しく確認" },
    { slug: "tarp-tent-layout-site-guide", reason: "テントとタープの配置を考える" },
  ],
  "snow-peak-amenity-dome-l-10year-review": [
    { slug: "landlock-vs-landnest-shelter", reason: "2ルームへの買い替えを比較" },
    { slug: "landnest-shelter-vs-2room-comparison", reason: "ほかの2ルームも見てみる" },
    { slug: "tarp-tent-layout-site-guide", reason: "タープと組み合わせて使う" },
  ],
  "portable-cooler-fan-guide": [
    { slug: "portable-power-station-guide", reason: "使う機器に合う電源を選ぶ" },
    { slug: "summer-camp-heat-gear-guide", reason: "日陰や風も含めて暑さに備える" },
  ],
  "tarp-tent-layout-site-guide": [
    { slug: "tarp-setup-guide-for-beginners", reason: "配置が決まったら張り方を確認" },
    { slug: "tarp-buying-guide", reason: "形とサイズからタープを選ぶ" },
    { slug: "family-tent-ranking", reason: "家族に合うテントも比較" },
  ],
  "snow-peak-landlock-x-review": [
    { slug: "landlock-vs-landnest-shelter", reason: "ランドロックの各モデルを比較" },
    { slug: "tarp-tent-layout-site-guide", reason: "サイト全体の配置を考える" },
    { slug: "snow-peak-amenity-dome-l-10year-review", reason: "長期使用の記録も読む" },
  ],
  "kids-sleeping-bag-ranking": [
    { slug: "spring-sleeping-bag-guide", reason: "季節と気温から寝袋を選ぶ" },
    { slug: "winter-camp-beginners-checklist", reason: "寝袋以外の冬支度も確認" },
  ],
  "family-tent-ranking": [
    { slug: "landlock-vs-landnest-shelter", reason: "気になる2ルームを詳しく比較" },
    { slug: "snow-peak-amenity-dome-l-10year-review", reason: "長く使った記録を読む" },
    { slug: "tarp-tent-layout-site-guide", reason: "テントとタープの配置を考える" },
  ],
};

const genericTags = new Set(["キャンプ", "アウトドア", "おすすめ", "ランキング", "比較", "レビュー", "ファミリーキャンプ", "子連れキャンプ"]);
const normalizeTag = (tag: string) => tag.normalize("NFKC").trim().toLowerCase();
const meaningfulTags = (tags: string[] = []) => new Set(tags.map(normalizeTag).filter((tag) => tag && !genericTags.has(tag) && !/^\d{4}(年|年版)?$/.test(tag)));
const timestamp = (value: string | null) => {
  const parsed = value ? Date.parse(value) : 0;
  return Number.isFinite(parsed) ? parsed : 0;
};

export function getNextReads(current: ArticleSummary, articles: ArticleSummary[], limit = 3): NextRead[] {
  if (limit <= 0) return [];
  const available = new Map<string, ArticleSummary>();
  const seenIds = new Set<string>();
  for (const article of articles) {
    if (article.status !== "published" || article.id === current.id || article.slug === current.slug || seenIds.has(article.id) || available.has(article.slug)) continue;
    available.set(article.slug, article);
    seenIds.add(article.id);
  }
  const result: NextRead[] = [];
  for (const link of NEXT_READS[current.slug] ?? []) {
    const article = available.get(link.slug);
    if (!article) continue;
    result.push({ article, reason: link.reason });
    available.delete(link.slug);
    if (result.length >= limit) return result;
  }
  const productIds = new Set(current.productIds ?? []);
  const tags = meaningfulTags(current.tags);
  const candidates = [...available.values()].map((article) => {
    const sharedProducts = [...new Set(article.productIds ?? [])].filter((id) => productIds.has(id)).length;
    const sharedTags = [...meaningfulTags(article.tags)].filter((tag) => tags.has(tag)).length;
    const sameCategory = Number(article.categoryId === current.categoryId);
    return { article, sharedProducts, sharedTags, sameCategory };
  }).filter(({ sharedProducts, sharedTags, sameCategory }) => sharedProducts || sharedTags || sameCategory)
    .sort((a, b) => b.sharedProducts - a.sharedProducts || b.sharedTags - a.sharedTags || b.sameCategory - a.sameCategory || timestamp(b.article.publishedAt) - timestamp(a.article.publishedAt) || a.article.slug.localeCompare(b.article.slug));
  for (const candidate of candidates.slice(0, limit - result.length)) {
    result.push({ article: candidate.article, reason: candidate.sharedProducts ? "同じギアを別の視点から読む" : candidate.sharedTags ? "同じテーマをもう少し詳しく" : "このカテゴリの選び方を広げる" });
  }
  return result;
}
