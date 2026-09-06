import type { Product } from "./types.ts";

export function hasProductComparison(content: string, products: Pick<Product, "id">[]): boolean {
  const available = new Set(products.map((product) => product.id));
  return [...content.matchAll(/\{\{comparison:([^}]+)\}\}/g)].some((match) =>
    match[1].split(",").some((id) => available.has(id.trim()))
  );
}

export type ArticleDestination = "toc" | "body" | "comparison" | "products" | "article";
export type ArticleNavigationArea = "reading_nav" | "next_reads";

/** Optional analytics must never interrupt a reader's navigation. */
export function trackArticleNavigation(
  articleSlug: string,
  destination: ArticleDestination,
  area: ArticleNavigationArea,
  targetSlug?: string,
) {
  if (typeof window === "undefined") return;
  try {
    const gtag = (window as unknown as { gtag?: (...args: unknown[]) => void }).gtag;
    if (typeof gtag !== "function") return;
    gtag("event", "article_navigation", {
      article_slug: articleSlug,
      navigation_area: area,
      destination,
      ...(targetSlug ? { target_slug: targetSlug } : {}),
    });
  } catch {
    // The anchor remains usable even if analytics is blocked or unavailable.
  }
}
