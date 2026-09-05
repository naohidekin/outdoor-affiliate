import type { Metadata } from "next";
import { toJsonLd } from "@/lib/jsonld";
import Image from "next/image";
import Link from "next/link";
import { getPublicCategories, getPublishedArticlesList, getProductsByIds } from "@/lib/db";
import GearGuideTopics from "@/components/GearGuideTopics";
import AffiliateLink from "@/components/AffiliateLink";
import { getAvailableGearGuides } from "@/lib/gearGuides";
import Header from "@/components/Header";
import Footer from "@/components/Footer";
import ArticleCard from "@/components/ArticleCard";
import { FEATURED_SLUGS, getPrimaryProducts, getSeasonalFeature } from "@/lib/articleEditorial";
import { getCategoryIcon } from "@/lib/category-icons";

export const revalidate = 21600; // ISR: 6時間（Egress削減・2026-07-24）

export const metadata: Metadata = {
  title: "家族のキャンプ道具選び｜小児科医・二児の父のCamp Gear Lab",
  description:
    "設営の負担、家族の寝心地、安全対策からキャンプ道具を選ぶ。小児科医・二児の父が、10年使った道具の記録と仕様比較、子連れキャンプの準備ガイドを届けます。",
  alternates: {
    canonical: "/",
  },
  openGraph: {
    title: "家族のキャンプ道具選び｜小児科医・二児の父のCamp Gear Lab",
    description:
      "現役小児科医・キャンプ歴10年の運営者が、家族で安全に楽しめるアウトドアギアを医師目線で比較・検証。",
    url: "/",
  },
};

export default async function Home() {
  const [categories, articles] = await Promise.all([
    getPublicCategories(),
    getPublishedArticlesList(),
  ]);

  const gearGuides = getAvailableGearGuides(articles);

  // 安全ガイド導線 4記事を特定
  const SAFETY_GUIDE_SLUGS = [
    "family-camp-safety-guide",
    "camp-insect-repellent-guide",
    "summer-camp-heat-gear-guide",
    "winter-camp-beginners-checklist",
  ] as const;
  const safetyGuideArticles = SAFETY_GUIDE_SLUGS
    .map((slug) => articles.find((a) => a.slug === slug))
    .filter((a): a is NonNullable<typeof a> => a !== undefined);

  const findArticles = (slugs: readonly string[]) => slugs
    .map((slug) => articles.find((article) => article.slug === slug))
    .filter((article): article is NonNullable<typeof article> => Boolean(article));
  const featuredArticles = findArticles(FEATURED_SLUGS);
  const fieldReview = findArticles(["snow-peak-amenity-dome-l-10year-review"])[0];
  const seasonal = getSeasonalFeature(Number(new Intl.DateTimeFormat("en", { month: "numeric", timeZone: "Asia/Tokyo" }).format(new Date())));
  const seasonalArticles = findArticles(seasonal.slugs);
  const latestArticles = [...articles]
    .sort((a, b) => new Date(b.publishedAt ?? 0).getTime() - new Date(a.publishedAt ?? 0).getTime())
    .slice(0, 3);

  // Fetch only the products needed by visible cards, not the entire archive.
  const displayedArticles = [...featuredArticles, ...latestArticles];
  const productIds = [...new Set(displayedArticles.flatMap((article) => article.productIds))];
  const products = productIds.length ? await getProductsByIds(productIds) : [];
  const productMap = new Map(products.map((product) => [product.id, product]));
  const thumbnailFor = (article: typeof articles[number]) => getPrimaryProducts(article,
    article.productIds.flatMap((id) => productMap.has(id) ? [productMap.get(id)!] : [])
  ).find((product) => product.imageUrl);

  const baseUrl = "https://camp-gear-lab.com";

  const webSiteJsonLd = {
    "@context": "https://schema.org",
    "@type": "WebSite",
    name: "Camp Gear Lab",
    alternateName: "キャンプギアラボ",
    url: baseUrl,
    description:
      "現役小児科医・キャンプ歴10年の運営者が、虫・暑さ・寒さ・食中毒・一酸化炭素など子ども連れキャンプのリスク視点でアウトドアギアを比較・検証。",
    publisher: {
      "@type": "Organization",
      name: "Camp Gear Lab",
      url: baseUrl,
    },
    author: {
      "@type": "Person",
      name: "ギア男",
      jobTitle: "小児科医（開業医）",
      description: "現役の小児科開業医「ギア男」。キャンプ歴10年、2児の父。医師目線で家族が安全に楽しめるアウトドアギアを比較・検証。",
      url: `${baseUrl}/about`,
      sameAs: [
        "https://x.com/camp_gear_lab",
        "https://twitter.com/camp_gear_lab",
        "https://room.rakuten.co.jp/room_naomaru",
      ],
    },
  };

  const organizationJsonLd = {
    "@context": "https://schema.org",
    "@type": "Organization",
    name: "Camp Gear Lab",
    alternateName: "キャンプギアラボ",
    url: baseUrl,
    logo: {
      "@type": "ImageObject",
      url: `${baseUrl}/logo.png`,
      width: 512,
      height: 512,
    },
    founder: {
      "@type": "Person",
      name: "ギア男",
      url: `${baseUrl}/about`,
    },
    sameAs: [
      "https://x.com/camp_gear_lab",
      "https://twitter.com/camp_gear_lab",
      "https://room.rakuten.co.jp/room_naomaru",
    ],
  };

  const collectionJsonLd = {
    "@context": "https://schema.org",
    "@type": "CollectionPage",
    name: "キャンプ・登山ギアおすすめ比較・レビュー",
    url: baseUrl,
    mainEntity: {
      "@type": "ItemList",
      itemListElement: [...new Map(displayedArticles.map((article) => [article.id, article])).values()].map((a, i) => ({
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
        dangerouslySetInnerHTML={{ __html: toJsonLd(webSiteJsonLd) }}
      />
      <script
        type="application/ld+json"
        dangerouslySetInnerHTML={{ __html: toJsonLd(organizationJsonLd) }}
      />
      <script
        type="application/ld+json"
        dangerouslySetInnerHTML={{ __html: toJsonLd(collectionJsonLd) }}
      />
      <Header categories={categories} />
      <main className="flex-1">
        <section className="border-b border-line bg-white">
          <div className="max-w-6xl mx-auto px-4 py-7 md:py-10 grid lg:grid-cols-[1.15fr_1fr] gap-8 lg:gap-14 items-center">
            <div>
              <p className="text-sm font-medium text-lake-600 mb-3">小児科医・二児の父のキャンプノート</p>
              <h1 className="text-3xl sm:text-4xl font-semibold text-ink-strong leading-[1.4] tracking-tight">
                家族の時間が増える、<br />キャンプ道具選び。
              </h1>
              <p className="mt-4 text-base text-slate-600 leading-loose max-w-xl">
                設営がラクか。子どもと眠れるか。安全に使えるか。<br className="hidden sm:block" />
                10年使った道具の記録と、買う前に知りたい比較を届けます。
              </p>
              <div className="mt-5"><GearGuideTopics guides={gearGuides} /></div>
              <div className="flex flex-wrap gap-x-5 gap-y-2 mt-4 text-sm">
                <Link href="/articles" className="inline-flex min-h-11 items-center text-lake-600 font-semibold hover:underline">商品名から記事を探す →</Link>
                <Link href="/about" className="inline-flex min-h-11 items-center text-slate-500 underline underline-offset-4">書き手と編集方針</Link>
              </div>
            </div>
            <div className="overflow-hidden rounded-2xl border border-line bg-snow">
              <div className="relative h-32 sm:h-48 lg:h-56">
                <Image src="https://images.unsplash.com/photo-1504280390367-361c6d9f38f4?w=1600&q=80" alt="" fill sizes="(min-width: 1024px) 500px, 100vw" className="object-cover" preload />
              </div>
              <div className="p-5 sm:p-6">
                <h2 className="text-lg font-semibold text-ink-strong">{seasonal.label}</h2>
                <p className="mt-1 text-sm text-slate-500">{seasonal.description}</p>
                <div className="mt-4 divide-y divide-line">
                  {seasonalArticles.map((article) => (
                    <Link key={article.id} href={`/articles/${article.slug}`} className="flex gap-3 justify-between py-3 text-sm font-medium leading-relaxed text-ink hover:text-lake-700">
                      <span className="line-clamp-2">{article.title}</span><span aria-hidden="true" className="text-lake-600 shrink-0">→</span>
                    </Link>
                  ))}
                  {seasonalArticles.length === 0 && <Link href="/articles" className="block py-3 text-sm text-lake-700">キャンプの準備ガイドを探す →</Link>}
                </div>
              </div>
            </div>
          </div>
        </section>

        <section id="gear-guides" className="max-w-6xl mx-auto px-4 py-12 md:py-16 scroll-mt-20">
          <div className="flex flex-wrap items-end justify-between gap-3 mb-7">
            <div><p className="text-xs text-lake-600 font-semibold tracking-widest mb-2">GEAR GUIDES</p><h2 className="text-2xl font-semibold text-ink-strong">買う前の迷いを、ここから。</h2><p className="text-sm text-slate-500 mt-2">広さ・設営・予算。家族の条件に合う一台を選ぶ。</p></div>
            <Link href="/articles" className="text-sm font-medium text-lake-600 hover:text-lake-700">すべての記事 →</Link>
          </div>
          <div className="grid sm:grid-cols-2 lg:grid-cols-3 gap-6">
            {featuredArticles.map((article) => <ArticleCard key={article.id} article={article} category={categories.find((category) => category.id === article.categoryId)} thumbnailProduct={thumbnailFor(article)} />)}
          </div>
        </section>

        <section id="field-notes" className="max-w-6xl mx-auto px-4 pb-12 scroll-mt-20">
          <div className="grid md:grid-cols-[1fr_2fr] overflow-hidden rounded-2xl border border-line bg-white">
            <div className="bg-lake-50 p-7 md:p-9 flex flex-col justify-between gap-6">
              <p className="text-xs font-semibold tracking-widest text-lake-700">FIELD NOTES</p>
              <div><p className="text-4xl font-semibold tracking-tight text-ink-strong">2016—2026</p><p className="mt-2 text-sm text-slate-600">家族と使い続けた道具の記録</p></div>
            </div>
            <div className="p-7 md:p-9">
              <h2 className="text-xl sm:text-2xl font-semibold leading-relaxed text-ink-strong">10年使ったテント。<br />次の一張りを、どう選んだか。</h2>
              <p className="mt-4 text-sm leading-loose text-slate-600">アメニティドームLを使ってきた父として、よかった点も、買い替えで重視したことも。長く使う道具を選ぶための手がかりを残します。</p>
              <div className="flex flex-wrap gap-x-6 gap-y-3 mt-5 text-sm font-semibold text-lake-600">
                {fieldReview && <Link href={`/articles/${fieldReview.slug}`} className="hover:underline underline-offset-4">10年レビューを読む →</Link>}
                {featuredArticles.some((article) => article.slug === "landlock-vs-landnest-shelter") && <Link href="/articles/landlock-vs-landnest-shelter" className="hover:underline underline-offset-4">買い替え候補の比較を読む →</Link>}
                <Link href="/about" className="hover:underline underline-offset-4">運営者について →</Link>
              </div>
            </div>
          </div>
        </section>

        {/* 安全ガイド導線 */}
        {safetyGuideArticles.length > 0 && (
          <section className="max-w-6xl mx-auto px-4 py-12 border-b border-line">
            <div className="mb-6">
              <h2 className="text-xl font-semibold text-ink-strong tracking-tight">
                子どもと出かける前に、確認したいこと
              </h2>
              <p className="text-sm text-slate-500 mt-1">小児科医の視点で整理する、虫・暑さ・寒さへの備え</p>
            </div>
            <div className="grid sm:grid-cols-2 gap-4">
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
                const thumbProduct = thumbnailFor(article);
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

        {/* Categories（記事数上位8件。全カテゴリ展開は縦に長くなりすぎるため
            残りは /articles のカテゴリ絞り込みへ誘導） */}
        <section className="max-w-6xl mx-auto px-4 py-16">
          <div className="flex items-end justify-between mb-8">
            <div>
              <h2 className="text-2xl font-semibold text-ink-strong tracking-tight">
                カテゴリから探す
              </h2>
              <p className="text-sm text-slate-500 mt-1">ジャンル別にギアを比較</p>
            </div>
            <Link
              href="/articles"
              className="text-sm text-lake-600 hover:text-lake-700 font-medium shrink-0"
            >
              すべてのカテゴリ →
            </Link>
          </div>
          <div className="grid sm:grid-cols-2 md:grid-cols-3 lg:grid-cols-4 gap-3">
            {categories
              .map((c) => ({
                c,
                count: c.articleSlugs
                  ? articles.filter((a) => c.articleSlugs!.includes(a.slug)).length
                  : articles.filter((a) => a.categoryId === c.id).length,
              }))
              .sort((a, b) => b.count - a.count)
              .slice(0, 8)
              .map(({ c, count: articleCount }) => {
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
          <div className="bg-white border border-line rounded-2xl p-6 sm:p-8">
            <div className="mb-5">
              <span className="inline-block text-xs font-semibold tracking-widest text-red-500 uppercase mb-2">楽天ROOM</span>
              <h2 className="text-xl font-semibold text-ink-strong">楽天ROOMのコレクション</h2>
              <p className="text-sm text-slate-500 mt-1">広告リンクを含みます。テーマ別に掲載した道具を販売店で確認できます。</p>
            </div>
            <div className="flex gap-3 overflow-x-auto pb-3 -mx-1 px-1 snap-x snap-mandatory scrollbar-hide" style={{ scrollbarWidth: "none", msOverflowStyle: "none", WebkitOverflowScrolling: "touch" }}>
              {/* 既存のROOMコレクションへの導線を維持 */}
              {[
                { label: "夏キャンプ 虫対策セット", desc: "蚊・ブヨ・アブ対策の定番ギアを厳選", icon: "🦟", href: "https://room.rakuten.co.jp/room_naomaru/1800012289285534" },
                { label: "子ども連れ 暑さ対策", desc: "扇風機・クーラー・日よけの涼感セット", icon: "☀️", href: "https://room.rakuten.co.jp/room_naomaru/1800012289288356" },
                { label: "初めてのファミリーキャンプ一式", desc: "テント〜チェアまで家族4人分をまとめて", icon: "👨‍👩‍👧‍👦", href: "https://room.rakuten.co.jp/room_naomaru/1800012289286225" },
                { label: "春秋キャンプ 寒さ対策", desc: "シュラフ〜ウェアの3シーズン防寒装備", icon: "🧥", href: "https://room.rakuten.co.jp/room_naomaru/1800012289289365" },
                { label: "焚き火まわりセット", desc: "焚き火台・リフレクター・鉄板を一式で", icon: "🔥", href: "https://room.rakuten.co.jp/room_naomaru/1800012447451128" },
                { label: "防災兼用 キャンプギア", desc: "停電・避難でも使えるアウトドア道具", icon: "🏕️", href: "https://room.rakuten.co.jp/room_naomaru/1800012289290411" },
              ].map(({ label, desc, icon, href }) => (
                <AffiliateLink
                  productId={`room-${href.split("/").pop()}`}
                  productName={label}
                  store="rakuten"
                  placement="room_collection"
                  key={label}
                  href={href}
                  className="flex-none w-[140px] sm:w-[160px] flex flex-col items-center gap-2 bg-white border border-red-100 rounded-xl p-4 text-center hover:border-red-300 hover:shadow-sm transition group snap-start"
                >
                  <span className="text-2xl">{icon}</span>
                  <span className="text-sm font-medium text-slate-700 group-hover:text-red-600 leading-snug">{label}</span>
                  <span className="text-xs text-slate-500 leading-snug line-clamp-2">{desc}</span>
                  <span className="text-xs text-red-400 font-medium mt-auto">楽天ROOMで見る →</span>
                </AffiliateLink>
              ))}
            </div>
          </div>
        </section>

        {/* 記事アーカイブへの導線。従来は全記事（100本超）をここに展開しており、
            トップが際限なく長くなっていた。一覧・検索・絞り込みは /articles に分離 */}
        {articles.length > 0 && (
          <section className="max-w-6xl mx-auto px-4 pb-20">
            <div className="bg-lake-50/60 border border-lake-100 rounded-2xl p-8 text-center">
              <h2 className="text-xl font-semibold text-ink-strong tracking-tight mb-2">
                お探しのギアが決まっていますか？
              </h2>
              <p className="text-sm text-slate-500 mb-5">
                全{articles.length}記事をキーワード・カテゴリから探せます
              </p>
              <Link
                href="/articles"
                className="inline-flex items-center gap-2 bg-lake-600 hover:bg-lake-700 text-white px-6 py-3 rounded-xl text-sm font-semibold transition"
              >
                すべての記事を見る →
              </Link>
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
