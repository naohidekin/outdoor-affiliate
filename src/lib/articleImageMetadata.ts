import type { Article } from "./types";

/** Explicit metadata owns the URL; the legacy fallback is an ordinary route. */
export function articleImageMetadata(article: Pick<Article, "slug" | "generationMeta">) {
  const url = article.generationMeta?.socialCard?.url || `/articles/${article.slug}/opengraph-image`;
  return {
    openGraph: { images: [{ url, width: 1200, height: 630 }] },
    twitter: { images: [url] },
  };
}
