import type { Metadata } from "next";
import Link from "next/link";
import { getCategories, getPublishedArticles, getProductsByIds } from "@/lib/db";
import Header from "@/components/Header";
import Footer from "@/components/Footer";
import ArticleCard from "@/components/ArticleCard";
import {
  Tent,
  Lamp,
  Flame,
  Backpack,
  Snowflake,
  Mountain,
  Armchair,
  Table,
  ThermometerSnowflake,
  Shirt,
  Footprints,
  Cloudy,
} from "lucide-react";

export const dynamic = "force-dynamic";

export const metadata: Metadata = {
  title: "キャンプ・登山ギアおすすめ比較・レビュー | Outdoor Gear Lab",
  description:
    "テント・シュラフ・バーナー・バックパック・登山靴など、キャンプ・登山ギアを徹底比較。スペック比較表・口コミ・ランキングで「どれ買えばいい？」を即解決。",
  alternates: {
    canonical: "/",
  },
  openGraph: {
    title: "キャンプ・登山ギアおすすめ比較・レビュー | Outdoor Gear Lab",
    description:
      "テント・シュラフ・バーナー・バックパック・登山靴など、キャンプ・登山ギアを徹底比較。",
    url: "/",
  },
};

const CATEGORY_ICON: Record<string, React.ReactNode> = {
  tent: <Tent className="w-6 h-6" />,
  lantern: <Lamp className="w-6 h-6" />,
  burner: <Flame className="w-6 h-6" />,
  backpack: <Backpack className="w-6 h-6" />,
  "sleeping-bag": <Snowflake className="w-6 h-6" />,
  shoes: <Footprints className="w-6 h-6" />,
  chair: <Armchair className="w-6 h-6" />,
  table: <Table className="w-6 h-6" />,
  cooler: <ThermometerSnowflake className="w-6 h-6" />,
  wear: <Shirt className="w-6 h-6" />,
  firepit: <Flame className="w-6 h-6" />,
  tarp: <Cloudy className="w-6 h-6" />,
};

export default async function Home() {
  const [categories, articles] = await Promise.all([
    getCategories(),
    getPublishedArticles(),
  ]);

  // ArticleCard用: 全記事の商品を一括取得してサムネイルを引き当て
  const allProductIds = [...new Set(articles.flatMap((a) => a.productIds))];
  const allProducts = allProductIds.length > 0
    ? await getProductsByIds(allProductIds)
    : [];
  const productMap = new Map(allProducts.map((p) => [p.id, p]));

  const baseUrl = "https://camp-gear-lab.com";

  const webSiteJsonLd = {
    "@context": "https://schema.org",
    "@type": "WebSite",
    name: "Outdoor Gear Lab",
    alternateName: "キャンプギアラボ",
    url: baseUrl,
    description:
      "テント・シュラフ・バーナー・バックパック・登山靴など、キャンプ・登山ギアを徹底比較。",
    publisher: {
      "@type": "Organization",
      name: "Outdoor Gear Lab",
      url: baseUrl,
    },
  };

  const collectionJsonLd = {
    "@context": "https://schema.org",
    "@type": "CollectionPage",
    name: "キャンプ・登山ギアおすすめ比較・レビュー",
    url: baseUrl,
    mainEntity: {
      "@type": "ItemList",
      itemListElement: articles.slice(0, 6).map((a, i) => ({
        "@type": "ListItem",
        position: i + 1,
        url: `${baseUrl}/articles/${a.slug}`,
        name: a.title,
      })),
    },
  };

  return (
    <>
      <script
        type="application/ld+json"
        dangerouslySetInnerHTML={{ __html: JSON.stringify(webSiteJsonLd) }}
      />
      <script
        type="application/ld+json"
        dangerouslySetInnerHTML={{ __html: JSON.stringify(collectionJsonLd) }}
      />
      <Header categories={categories} />
      <main className="flex-1">
        {/* Hero */}
        <section className="relative bg-ink-strong text-white overflow-hidden border-b border-line">
          <div
            className="absolute inset-0 opacity-25"
            style={{
              backgroundImage: "url('https://images.unsplash.com/photo-1504280390367-361c6d9f38f4?w=1600&q=80')",
              backgroundSize: "cover",
              backgroundPosition: "center 40%",
            }}
          />
          <div className="absolute inset-0 bg-gradient-to-t from-ink-strong via-ink-strong/70 to-ink-strong/30" />
          <div className="max-w-6xl mx-auto px-4 py-24 md:py-32 relative">
            <p className="text-lake-200 font-medium text-xs tracking-[0.25em] uppercase mb-4">
              Gear Reviews & Comparisons
            </p>
            <h1 className="text-3xl md:text-5xl font-semibold mb-5 leading-tight tracking-tight">
              買う前に、
              <br className="md:hidden" />
              徹底的に比較する。
            </h1>
            <p className="text-slate-300 text-base md:text-lg max-w-lg leading-relaxed">
              テント・シュラフ・バーナー・チェア。キャンプギアのスペック比較と正直レビューで「どれ買えばいい？」を解決する。
            </p>
            <div className="flex flex-wrap gap-2 mt-8">
              {categories.slice(0, 6).map((c) => (
                <Link
                  key={c.id}
                  href={`/category/${c.slug}`}
                  className="flex items-center gap-1.5 bg-white/5 hover:bg-white/10 text-white/90 hover:text-white px-4 py-2 rounded-full text-sm transition border border-white/15 hover:border-lake-200"
                >
                  <span className="text-lake-200">{CATEGORY_ICON[c.slug] ?? <Mountain className="w-4 h-4" />}</span>
                  {c.name}
                </Link>
              ))}
            </div>
          </div>
        </section>

        {/* Categories */}
        <section className="max-w-6xl mx-auto px-4 py-16">
          <div className="flex items-end justify-between mb-8">
            <div>
              <h2 className="text-2xl font-semibold text-ink-strong tracking-tight">
                カテゴリから探す
              </h2>
              <p className="text-sm text-slate-500 mt-1">ジャンル別にギアを比較</p>
            </div>
          </div>
          <div className="grid sm:grid-cols-2 md:grid-cols-3 lg:grid-cols-4 gap-3">
            {categories.map((c) => {
              const articleCount = articles.filter(
                (a) => a.categoryId === c.id
              ).length;
              return (
                <Link
                  key={c.id}
                  href={`/category/${c.slug}`}
                  className="bg-white rounded-xl transition-all p-5 border border-line hover:border-lake-200 hover:bg-lake-50/30 group flex items-start gap-4"
                >
                  <div className="w-10 h-10 rounded-lg flex items-center justify-center shrink-0 bg-lake-50 text-lake-600 border border-lake-100 transition-colors group-hover:bg-lake-100">
                    {CATEGORY_ICON[c.slug] ?? <Mountain className="w-5 h-5" />}
                  </div>
                  <div className="min-w-0">
                    <h3 className="font-semibold text-ink-strong text-sm group-hover:text-lake-700 transition">
                      {c.name}
                    </h3>
                    <p className="text-xs text-slate-500 mt-0.5">
                      {articleCount}件の記事
                    </p>
                  </div>
                </Link>
              );
            })}
          </div>
        </section>

        {/* Latest Articles */}
        {articles.length > 0 && (
          <section className="max-w-6xl mx-auto px-4 pb-20">
            <div className="flex items-end justify-between mb-8">
              <div>
                <h2 className="text-2xl font-semibold text-ink-strong tracking-tight">
                  記事一覧
                </h2>
                <p className="text-sm text-slate-500 mt-1">スペック比較・レビュー・選び方ガイド</p>
              </div>
            </div>
            <div className="grid sm:grid-cols-2 lg:grid-cols-3 gap-5">
              {articles.map((article) => {
                const cat = categories.find(
                  (c) => c.id === article.categoryId
                );
                return (
                  <ArticleCard
                    key={article.id}
                    article={article}
                    category={cat}
                    thumbnailProduct={article.productIds
                      .map((id) => productMap.get(id))
                      .find((p) => p?.imageUrl)}
                  />
                );
              })}
            </div>
          </section>
        )}

        {/* Empty state */}
        {articles.length === 0 && (
          <section className="max-w-6xl mx-auto px-4 pb-16 text-center">
            <div className="bg-mist rounded-xl p-12 border border-line">
              <p className="text-slate-500 text-lg mb-4">
                まだ記事が公開されていません
              </p>
              <Link
                href="/admin"
                className="text-lake-600 hover:text-lake-700 font-medium"
              >
                管理画面から記事を作成 →
              </Link>
            </div>
          </section>
        )}
      </main>
      <Footer />
    </>
  );
}
