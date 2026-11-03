import test from "node:test";
import assert from "node:assert/strict";
import { articleImageMetadata } from "../src/lib/articleImageMetadata.ts";

test("approved stored social card owns both OG and Twitter URL without resizing", () => {
  const url = "https://project.supabase.co/storage/v1/object/public/editorial-social-cards/aa/" + "a".repeat(64) + ".png";
  const article = { slug: "new-article", generationMeta: {
    themeId: "theme", model: "writer", retryCount: 0, generatedAt: "2026-11-03T23:00:00+09:00",
    socialCard: { url, sha256: "a".repeat(64), size: 100, contentType: "image/png", width: 1200, height: 630, templateVersion: "v1", sources: [] },
  } };
  assert.deepEqual(articleImageMetadata(article), {
    openGraph: { images: [{ url, width: 1200, height: 630 }] }, twitter: { images: [url] },
  });
  assert.equal(article.generationMeta.socialCard.url, url);
});

test("legacy published articles retain their own unchanged green fallback URL", () => {
  assert.deepEqual(articleImageMetadata({ slug: "old-article" }), {
    openGraph: { images: [{ url: "/articles/old-article/opengraph-image", width: 1200, height: 630 }] },
    twitter: { images: ["/articles/old-article/opengraph-image"] },
  });
});
