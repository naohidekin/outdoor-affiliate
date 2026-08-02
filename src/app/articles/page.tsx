import type { Metadata } from "next";
import Link from "next/link";
import { toJsonLd } from "@/lib/jsonld";
import { getPublicCategories, getPublishedArticlesList, getProductsByIds } from "@/lib/db";
import Header from "@/components/Header";
import Footer from "@/components/Footer";
import ArticleArchive from "@/components/ArticleArchive";
import { Product } from "@/lib/types";

export const revalidate = 21600; // ISR: 6時間（記事ページと同じ）

export const metadata: Metadata = {
  title: "記事一覧",
  description:
    "Camp Gear Labの全記事一覧。テント・シュラフ・バーナー・虫除けなど、キャンプ・登山ギアの比較レビューと選び方ガイドをカテゴリ・キーワードから探せます。",
  alternates: { canonical: "/articles" },
};

export default async function ArticlesPage() {
  const [categories, articles] = await Promise.all([
    getPublicCategories(),
    getPublishedArticlesList(),
  ]);

  const sorted = [...articles].sort(
    (a, b) =>
      new Date(b.publishedAt ?? 0).getTime() -
      new Date(a.publishedAt ?? 0).getTime()
  );

  // サムネイル用商品を一括取得（記事ごとに画像を持つ最初の商品）
  const allProductIds = [...new Set(sorted.flatMap((a) => a.productIds))];
  const allProducts =
    allProductIds.length > 0 ? await getProductsByIds(allProductIds) : [];
  const productMap = new Map(allProducts.map((p) => [p.id, p]));
  const thumbs: Record<string, Product | undefined> = {};
  for (const a of sorted) {
    thumbs[a.id] = a.productIds
      .map((id) => productMap.get(id))
      .find((p) => p?.imageUrl);
  }

  // クライアントへ渡すペイロードから本文を除く（全108記事分の全文は不要）
  const slim = sorted.map((a) => ({ ...a, content: "" }));

  const baseUrl = "https://camp-gear-lab.com";
  const collectionJsonLd = {
    "@context": "https://schema.org",
    "@type": "CollectionPage",
    name: "記事一覧 | Camp Gear Lab",
    url: `${baseUrl}/articles`,
    mainEntity: {
      "@type": "ItemList",
      itemListElement: sorted.slice(0, 20).map((a, i) => ({
        "@type": "ListItem",
        position: i + 1,
        url: `${baseUrl}/articles/${a.slug}`,
        name: a.title,
      })),
    },
  };
  const breadcrumbJsonLd = {
    "@context": "https://schema.org",
    "@type": "BreadcrumbList",
    itemListElement: [
      { "@type": "ListItem", position: 1, name: "ホーム", item: baseUrl },
      { "@type": "ListItem", position: 2, name: "記事一覧" },
    ],
  };

  return (
    <>
      <script
        type="application/ld+json"
        dangerouslySetInnerHTML={{ __html: toJsonLd(collectionJsonLd) }}
      />
      <script
        type="application/ld+json"
        dangerouslySetInnerHTML={{ __html: toJsonLd(breadcrumbJsonLd) }}
      />
      <Header categories={categories} />
      <main className="flex-1">
        <div className="max-w-6xl mx-auto px-4 py-12">
          <nav className="text-sm text-slate-500 mb-6" aria-label="パンくず">
            <Link href="/" className="hover:text-lake-600 transition">
              ホーム
            </Link>
            <span className="mx-2 text-slate-400">/</span>
            <span>記事一覧</span>
          </nav>

          <div className="mb-8">
            <h1 className="text-3xl font-semibold text-ink-strong tracking-tight">
              記事一覧
            </h1>
            <p className="text-sm text-slate-500 mt-2">
              全{sorted.length}記事。キーワードかカテゴリで絞り込めます
            </p>
          </div>

          <ArticleArchive
            articles={slim}
            categories={categories}
            thumbs={thumbs}
          />
        </div>
      </main>
      <Footer categories={categories} />
    </>
  );
}
