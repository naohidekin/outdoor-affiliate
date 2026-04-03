import type { Metadata } from "next";
import Link from "next/link";
import { getCategories, getPublishedArticles } from "@/lib/db";
import Header from "@/components/Header";
import Footer from "@/components/Footer";
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

const CATEGORY_COLOR: Record<string, string> = {
  tent: "#4a6741",
  lantern: "#b8860b",
  burner: "#c75b39",
  backpack: "#5a6e8a",
  "sleeping-bag": "#6b5b8a",
  shoes: "#7a6b5a",
  chair: "#5a7a6b",
  table: "#8a7a5a",
  cooler: "#4a7a8a",
  wear: "#6a5a7a",
  firepit: "#c75b39",
  tarp: "#5a7a6b",
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
        <section className="relative bg-[#2a2320] text-white overflow-hidden">
          <div
            className="absolute inset-0 opacity-30"
            style={{
              backgroundImage: "url('https://images.unsplash.com/photo-1504280390367-361c6d9f38f4?w=1600&q=80')",
              backgroundSize: "cover",
              backgroundPosition: "center 40%",
            }}
          />
          <div className="absolute inset-0 bg-gradient-to-t from-[#2a2320] via-[#2a2320]/60 to-transparent" />
          <div className="max-w-6xl mx-auto px-4 py-24 md:py-32 relative">
            <p className="text-[#7a9a6d] font-medium text-sm tracking-widest uppercase mb-4" style={{ fontFamily: 'var(--font-heading)' }}>
              Gear Reviews & Comparisons
            </p>
            <h1 className="text-3xl md:text-5xl font-bold mb-5 leading-tight tracking-tight">
              買う前に、
              <br className="md:hidden" />
              徹底的に比較する。
            </h1>
            <p className="text-gray-400 text-base md:text-lg max-w-lg leading-relaxed">
              テント・シュラフ・バーナー・チェア。キャンプギアのスペック比較と正直レビューで「どれ買えばいい？」を解決する。
            </p>
            <div className="flex flex-wrap gap-2 mt-8">
              {categories.slice(0, 6).map((c) => (
                <Link
                  key={c.id}
                  href={`/category/${c.slug}`}
                  className="flex items-center gap-1.5 bg-white/10 hover:bg-white/20 text-white/90 hover:text-white px-4 py-2 rounded-full text-sm transition border border-white/10 hover:border-white/20"
                >
                  <span className="text-[#7a9a6d]">{CATEGORY_ICON[c.slug] ?? <Mountain className="w-4 h-4" />}</span>
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
              <h2 className="text-2xl font-bold text-[#3d2b1f] tracking-tight">
                カテゴリから探す
              </h2>
              <p className="text-sm text-gray-500 mt-1">ジャンル別にギアを比較</p>
            </div>
          </div>
          <div className="grid sm:grid-cols-2 md:grid-cols-3 lg:grid-cols-4 gap-3">
            {categories.map((c) => {
              const articleCount = articles.filter(
                (a) => a.categoryId === c.id
              ).length;
              const color = CATEGORY_COLOR[c.slug] ?? "#4a6741";
              return (
                <Link
                  key={c.id}
                  href={`/category/${c.slug}`}
                  className="bg-white rounded-xl hover:shadow-md transition-all p-5 border border-gray-100 hover:border-gray-200 group flex items-start gap-4"
                >
                  <div
                    className="w-10 h-10 rounded-lg flex items-center justify-center shrink-0 transition-colors"
                    style={{ backgroundColor: `${color}12`, color }}
                  >
                    {CATEGORY_ICON[c.slug] ?? <Mountain className="w-5 h-5" />}
                  </div>
                  <div className="min-w-0">
                    <h3 className="font-bold text-gray-800 text-sm group-hover:text-[#4a6741] transition">
                      {c.name}
                    </h3>
                    <p className="text-xs text-gray-400 mt-0.5">
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
                <h2 className="text-2xl font-bold text-[#3d2b1f] tracking-tight">
                  記事一覧
                </h2>
                <p className="text-sm text-gray-500 mt-1">スペック比較・レビュー・選び方ガイド</p>
              </div>
            </div>
            <div className="grid sm:grid-cols-2 lg:grid-cols-3 gap-4">
              {articles.map((article) => {
                const cat = categories.find(
                  (c) => c.id === article.categoryId
                );
                const color = cat ? (CATEGORY_COLOR[cat.slug] ?? "#4a6741") : "#4a6741";
                return (
                  <Link
                    key={article.id}
                    href={`/articles/${article.slug}`}
                    className="bg-white rounded-xl hover:shadow-md transition-all overflow-hidden border border-gray-100 hover:border-gray-200 group"
                  >
                    {/* Color accent bar */}
                    <div className="h-1" style={{ backgroundColor: color }} />
                    <div className="p-5">
                      {cat && (
                        <div className="flex items-center gap-1.5 mb-3">
                          <span style={{ color }} className="opacity-70">
                            {CATEGORY_ICON[cat.slug] ?? <Mountain className="w-3.5 h-3.5" />}
                          </span>
                          <span className="text-xs font-medium text-gray-500">
                            {cat.name}
                          </span>
                        </div>
                      )}
                      <h3 className="font-bold text-gray-800 text-[15px] leading-snug mb-2 line-clamp-2 group-hover:text-[#4a6741] transition">
                        {article.title}
                      </h3>
                      <p className="text-sm text-gray-500 line-clamp-2 leading-relaxed">
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
            <div className="bg-gray-50 rounded-xl p-12 border border-gray-100">
              <p className="text-gray-500 text-lg mb-4">
                まだ記事が公開されていません
              </p>
              <Link
                href="/admin"
                className="text-[#4a6741] hover:text-[#5a7a51] font-medium"
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
