import type { Metadata } from "next";
import Link from "next/link";
import { getCategories, getPublishedArticles } from "@/lib/db";
import Header from "@/components/Header";
import Footer from "@/components/Footer";

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

const CATEGORY_EMOJI: Record<string, string> = {
  tent: "⛺",
  lantern: "🏮",
  burner: "🔥",
  backpack: "🎒",
  "sleeping-bag": "🧥",
  shoes: "👟",
  chair: "🪑",
  table: "🪵",
  cooler: "🧊",
  apparel: "👕",
  firepit: "🔥",
};

export default function Home() {
  const categories = getCategories();
  const articles = getPublishedArticles();

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
        <section className="bg-gradient-to-br from-amber-700 via-amber-600 to-green-700 text-white py-20 relative overflow-hidden">
          <div className="absolute inset-0 opacity-10 bg-[url('data:image/svg+xml;base64,PHN2ZyB3aWR0aD0iNjAiIGhlaWdodD0iNjAiIHhtbG5zPSJodHRwOi8vd3d3LnczLm9yZy8yMDAwL3N2ZyI+PGNpcmNsZSBjeD0iMzAiIGN5PSIzMCIgcj0iMiIgZmlsbD0id2hpdGUiLz48L3N2Zz4=')]"></div>
          <div className="max-w-6xl mx-auto px-4 text-center relative">
            <div className="text-5xl mb-4">⛺</div>
            <h1 className="text-4xl md:text-5xl font-bold mb-4 drop-shadow">
              Outdoor Gear Lab
            </h1>
            <p className="text-lg text-amber-100 mb-2">
              「どれ買えばいい？」その悩み、ここで解決。
            </p>
            <p className="text-sm text-amber-200 mb-8">
              実際に使って分かったリアルな比較・レビューをお届けします
            </p>
            <div className="flex flex-wrap justify-center gap-3">
              {categories.map((c) => (
                <Link
                  key={c.id}
                  href={`/category/${c.slug}`}
                  className="bg-white/20 hover:bg-white/35 text-white px-5 py-2 rounded-full text-sm transition backdrop-blur font-medium border border-white/30"
                >
                  {CATEGORY_EMOJI[c.slug] ?? "🏕️"} {c.name}
                </Link>
              ))}
            </div>
          </div>
        </section>

        {/* Categories */}
        <section className="max-w-6xl mx-auto px-4 py-16">
          <h2 className="text-2xl font-bold text-amber-900 mb-2">
            カテゴリから探す
          </h2>
          <p className="text-sm text-amber-700 mb-8">気になるジャンルをタップ！</p>
          <div className="grid sm:grid-cols-2 md:grid-cols-3 gap-5">
            {categories.map((c) => {
              const articleCount = articles.filter(
                (a) => a.categoryId === c.id
              ).length;
              return (
                <Link
                  key={c.id}
                  href={`/category/${c.slug}`}
                  className="bg-white rounded-2xl shadow-sm hover:shadow-md transition p-6 border border-amber-100 hover:border-amber-300 group"
                >
                  <div className="text-3xl mb-3">
                    {CATEGORY_EMOJI[c.slug] ?? "🏕️"}
                  </div>
                  <h3 className="font-bold text-gray-800 text-lg mb-1 group-hover:text-green-700 transition">
                    {c.name}
                  </h3>
                  <p className="text-sm text-gray-500 mb-3">{c.description}</p>
                  <span className="text-xs text-amber-700 font-medium">
                    {articleCount}件の記事 →
                  </span>
                </Link>
              );
            })}
          </div>
        </section>

        {/* Latest Articles */}
        {articles.length > 0 && (
          <section className="max-w-6xl mx-auto px-4 pb-16">
            <h2 className="text-2xl font-bold text-amber-900 mb-2">
              新着・人気の記事
            </h2>
            <p className="text-sm text-amber-700 mb-8">まずはこの記事から読んでみて！</p>
            <div className="grid sm:grid-cols-2 lg:grid-cols-3 gap-5">
              {articles.map((article) => {
                const cat = categories.find(
                  (c) => c.id === article.categoryId
                );
                return (
                  <Link
                    key={article.id}
                    href={`/articles/${article.slug}`}
                    className="bg-white rounded-2xl shadow-sm hover:shadow-md transition overflow-hidden border border-amber-100 hover:border-amber-300 group"
                  >
                    <div className="bg-gradient-to-r from-amber-50 to-green-50 px-6 pt-5 pb-2">
                      {cat && (
                        <span className="inline-block text-xs text-amber-700 font-semibold bg-amber-100 px-2 py-0.5 rounded-full">
                          {CATEGORY_EMOJI[cat.slug] ?? "🏕️"} {cat.name}
                        </span>
                      )}
                    </div>
                    <div className="px-6 pb-6 pt-3">
                      <h3 className="font-bold text-gray-800 mb-2 line-clamp-2 group-hover:text-green-700 transition">
                        {article.title}
                      </h3>
                      <p className="text-sm text-gray-500 line-clamp-3">
                        {article.excerpt}
                      </p>
                      <p className="text-xs text-gray-400 mt-3">
                        {article.publishedAt &&
                          new Date(article.publishedAt).toLocaleDateString(
                            "ja-JP"
                          )}
                      </p>
                    </div>
                  </Link>
                );
              })}
            </div>
          </section>
        )}

        {/* Empty state */}
        {articles.length === 0 && (
          <section className="max-w-6xl mx-auto px-4 pb-16 text-center">
            <div className="bg-amber-50 rounded-2xl p-12 border border-amber-100">
              <p className="text-amber-700 text-lg mb-4">
                まだ記事が公開されていません
              </p>
              <Link
                href="/admin"
                className="text-green-600 hover:text-green-700 font-medium"
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
