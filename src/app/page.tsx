import type { Metadata } from "next";
import Link from "next/link";
import { getCategories, getPublishedArticles, getProductsByIds } from "@/lib/db";
import Header from "@/components/Header";
import Footer from "@/components/Footer";
import ArticleCard from "@/components/ArticleCard";
import { getCategoryIcon } from "@/lib/category-icons";

export const revalidate = 3600; // ISR: 1時間

export const metadata: Metadata = {
  title: "現役小児科医が選ぶ、家族で安全に楽しむアウトドアギア | Outdoor Gear Lab",
  description:
    "現役小児科医・キャンプ歴10年の運営者が、家族で安全に楽しめるアウトドアギアを医師目線で比較・検証。子連れキャンプの救急対策、熱中症予防、虫除け選びなど、安全性を重視した実用レビューサイトです。",
  alternates: {
    canonical: "/",
  },
  openGraph: {
    title: "現役小児科医が選ぶ、家族で安全に楽しむアウトドアギア | Outdoor Gear Lab",
    description:
      "現役小児科医・キャンプ歴10年の運営者が、家族で安全に楽しめるアウトドアギアを医師目線で比較・検証。",
    url: "/",
  },
};

export default async function Home() {
  const [categories, articles] = await Promise.all([
    getCategories(),
    getPublishedArticles(),
  ]);

  // 安全ガイド導線 4記事を特定
  const SAFETY_GUIDE_SLUGS = [
    "camp-insect-repellent-roadmap",
    "summer-camp-heat-food-safety",
    "winter-camp-co-safety-guide",
    "family-camp-first-time-guide",
  ] as const;
  const safetyGuideArticles = SAFETY_GUIDE_SLUGS
    .map((slug) => articles.find((a) => a.slug === slug))
    .filter((a): a is NonNullable<typeof a> => a !== undefined);

  // ArticleCard用: 全記事の商品を一括取得してサムネイルを引き当て
  const allProductIds = [...new Set(articles.flatMap((a) => a.productIds))];
  const allProducts = allProductIds.length > 0
    ? await getProductsByIds(allProductIds)
    : [];
  const productMap = new Map(allProducts.map((p) => [p.id, p]));

  // 新着記事: publishedAt 降順で最新6件
  const latestArticles = [...articles]
    .sort((a, b) => new Date(b.publishedAt ?? 0).getTime() - new Date(a.publishedAt ?? 0).getTime())
    .slice(0, 6);

  const baseUrl = "https://camp-gear-lab.com";

  const webSiteJsonLd = {
    "@context": "https://schema.org",
    "@type": "WebSite",
    name: "Outdoor Gear Lab",
    alternateName: "キャンプギアラボ",
    url: baseUrl,
    description:
      "現役小児科医・キャンプ歴10年の運営者が、虫・暑さ・寒さ・食中毒・一酸化炭素など子ども連れキャンプのリスク視点でアウトドアギアを比較・検証。",
    publisher: {
      "@type": "Organization",
      name: "Outdoor Gear Lab",
      url: baseUrl,
    },
    author: {
      "@type": "Person",
      name: "現役小児科開業医",
      description: "現役の小児科開業医。キャンプ歴10年、2児の父。医師目線で家族が安全に楽しめるアウトドアギアを比較・検証。",
      url: `${baseUrl}/about`,
      sameAs: [
        "https://twitter.com/camp_gear_lab",
        `${baseUrl}/about`,
      ],
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
              現役小児科医が選ぶ、
              <br />
              家族で安全に楽しむアウトドアギア
            </h1>
            <p className="text-slate-300 text-base md:text-lg max-w-lg leading-relaxed">
              虫・暑さ・寒さ・食中毒・一酸化炭素。子ども連れキャンプで本当に気をつけたいリスクからギアを選びます。
            </p>
            {/* 3本柱カード */}
            <div className="grid grid-cols-1 sm:grid-cols-3 gap-3 mt-7 max-w-2xl">
              <div className="bg-white/8 border border-white/15 rounded-xl p-4">
                <p className="text-lake-200 font-semibold text-sm mb-1">🩺 医師目線で安全性をチェック</p>
                <p className="text-white/70 text-xs leading-relaxed">虫刺され、熱中症、低体温、食中毒、一酸化炭素など、本当に気をつけたいリスクからギアを選びます。</p>
              </div>
              <div className="bg-white/8 border border-white/15 rounded-xl p-4">
                <p className="text-lake-200 font-semibold text-sm mb-1">🏕️ キャンプ歴10年の実体験で選ぶ</p>
                <p className="text-white/70 text-xs leading-relaxed">カタログスペックだけでなく、設営・撤収・収納・子どもの使いやすさまで確認します。</p>
              </div>
              <div className="bg-white/8 border border-white/15 rounded-xl p-4">
                <p className="text-lake-200 font-semibold text-sm mb-1">📋 迷ったらすぐ選べる比較表</p>
                <p className="text-white/70 text-xs leading-relaxed">予算別・年齢別・季節別に、最初に買う候補を絞って紹介します。</p>
              </div>
            </div>
            <div className="flex flex-wrap gap-2 mt-8">
              {categories.slice(0, 6).map((c) => (
                <Link
                  key={c.id}
                  href={`/category/${c.slug}`}
                  className="flex items-center gap-1.5 bg-white/5 hover:bg-white/10 text-white/90 hover:text-white px-4 py-2 rounded-full text-sm transition border border-white/15 hover:border-lake-200"
                >
                  <span className="text-lake-200">{getCategoryIcon(c.slug, "sm")}</span>
                  {c.name}
                </Link>
              ))}
            </div>
          </div>
        </section>

        {/* 新着記事 */}
        {latestArticles.length > 0 && (
          <section className="max-w-6xl mx-auto px-4 py-12 border-b border-line">
            <div className="mb-6">
              <h2 className="text-2xl font-semibold text-ink-strong tracking-tight">新着記事</h2>
              <p className="text-sm text-slate-500 mt-1">最近追加されたギアレビュー・ガイド</p>
            </div>
            <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-6">
              {latestArticles.map((article) => {
                const cat = categories.find((c) => c.id === article.categoryId);
                const thumbPid = article.productIds[0];
                const thumbProduct = thumbPid ? productMap.get(thumbPid) : undefined;
                return (
                  <ArticleCard
                    key={article.id}
                    article={article}
                    category={cat}
                    thumbnailProduct={thumbProduct}
                  />
                );
              })}
            </div>
          </section>
        )}

        {/* 安全ガイド導線 */}
        {safetyGuideArticles.length > 0 && (
          <section className="max-w-6xl mx-auto px-4 py-12 border-b border-line">
            <div className="mb-6">
              <h2 className="text-xl font-semibold text-ink-strong tracking-tight">
                まず読むべき安全ギアガイド
              </h2>
              <p className="text-sm text-slate-500 mt-1">子連れキャンプの入口として</p>
            </div>
            <div className="grid sm:grid-cols-2 lg:grid-cols-4 gap-4">
              {safetyGuideArticles.map((article) => (
                <Link
                  key={article.id}
                  href={`/articles/${article.slug}`}
                  className="group bg-white rounded-xl border border-line hover:border-lake-200 hover:bg-lake-50/30 p-5 flex flex-col gap-2 transition-all"
                >
                  <p className="font-semibold text-sm text-ink-strong group-hover:text-lake-700 leading-snug transition">
                    {article.title}
                  </p>
                  {article.excerpt && (
                    <p className="text-xs text-slate-500 leading-relaxed line-clamp-2">
                      {article.excerpt}
                    </p>
                  )}
                  <span className="text-lake-600 text-xs font-medium mt-auto">
                    読む →
                  </span>
                </Link>
              ))}
            </div>
          </section>
        )}

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
              const articleCount = c.articleSlugs
                ? articles.filter((a) => c.articleSlugs!.includes(a.slug)).length
                : articles.filter((a) => a.categoryId === c.id).length;
              return (
                <Link
                  key={c.id}
                  href={`/category/${c.slug}`}
                  className="bg-white rounded-xl transition-all p-5 border border-line hover:border-lake-200 hover:bg-lake-50/30 group flex items-start gap-4"
                >
                  <div className="w-10 h-10 rounded-lg flex items-center justify-center shrink-0 bg-lake-50 text-lake-600 border border-lake-100 transition-colors group-hover:bg-lake-100">
                    {getCategoryIcon(c.slug, "md")}
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

        {/* 楽天ROOM まとめ買い導線 */}
        <section className="max-w-6xl mx-auto px-4 pb-16">
          <div className="bg-gradient-to-r from-red-50 to-rose-50 border border-red-100 rounded-2xl p-8">
            <div className="mb-6">
              <span className="inline-block text-xs font-semibold tracking-widest text-red-500 uppercase mb-2">楽天ROOM</span>
              <h2 className="text-xl font-semibold text-ink-strong">テーマ別ギアをまとめて見る</h2>
              <p className="text-sm text-slate-500 mt-1">シーン・家族構成別にまとめたコレクション。気になるセットをチェック。</p>
            </div>
            <div className="grid sm:grid-cols-2 lg:grid-cols-5 gap-3">
              {[
                { label: "夏キャンプ 虫対策セット", icon: "🦟", href: "https://room.rakuten.co.jp/room_naomaru/1800012289285534" },
                { label: "初めてのファミリーキャンプ一式", icon: "👨‍👩‍👧‍👦", href: "https://room.rakuten.co.jp/room_naomaru/1800012289286225" },
                { label: "子ども連れ 暑さ対策", icon: "☀️", href: "https://room.rakuten.co.jp/room_naomaru/1800012289288356" },
                { label: "春秋キャンプ 寒さ対策", icon: "🧥", href: "https://room.rakuten.co.jp/room_naomaru/1800012289289365" },
                { label: "防災兼用 キャンプギア", icon: "🏕️", href: "https://room.rakuten.co.jp/room_naomaru/1800012289290411" },
              ].map(({ label, icon, href }) => (
                <a
                  key={label}
                  href={href}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="flex flex-col items-center gap-2 bg-white border border-red-100 rounded-xl p-4 text-center hover:border-red-300 hover:shadow-sm transition group"
                >
                  <span className="text-2xl">{icon}</span>
                  <span className="text-xs font-medium text-slate-700 group-hover:text-red-600 leading-snug">{label}</span>
                  <span className="text-xs text-red-400 font-medium">楽天ROOMで見る →</span>
                </a>
              ))}
            </div>
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
      <Footer categories={categories} />
    </>
  );
}
