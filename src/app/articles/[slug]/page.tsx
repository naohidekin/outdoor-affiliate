import type { Metadata } from "next";
import { toJsonLd } from "@/lib/jsonld";
import Link from "next/link";
import { draftMode } from "next/headers";
import { notFound } from "next/navigation";
import {
  getCategories,
  getPublishedArticlesList,
  getArticleBySlug,
  getProductsByIds,
  getCategoryById,
  getArticlesByCategory,
} from "@/lib/db";
import Header from "@/components/Header";
import Footer from "@/components/Footer";
import ArticleContent from "@/components/ArticleContent";
import MedicalAdvice from "@/components/MedicalAdvice";
import RecommendationCTA from "@/components/RecommendationCTA";
import AffiliateDisclosure from "@/components/AffiliateDisclosure";
import { MEDICAL_ADVICE_MAP } from "@/lib/medicalAdviceData";
import HeroImage from "@/components/HeroImage";
import RakutenDealBadge from "@/components/RakutenDealBadge";

export const revalidate = 21600; // ISR: 6時間（Egress削減・2026-07-24）

// 下書きプレビューは searchParams ではなく Draft Mode（__prerender_bypass Cookie）で行う。
// searchParams はリクエスト時APIのため、参照するだけでページが動的レンダリングに落ち、
// 上の revalidate が無効化される（2026-08-01に全記事ページがSSRになっていた事故の原因）。
// Draft Mode ならCookie保持者だけがキャッシュをバイパスし、通常訪問者はISRのまま。
// 副次効果として、Cookieを持たないクローラーは下書きに到達できずインデックス事故も防げる。

// 全公開記事をビルド時にプリレンダーする。Supabase未接続などで失敗しても
// ビルドは通し、その場合はオンデマンド生成＋ISRにフォールバックさせる。
export async function generateStaticParams() {
  try {
    const articles = await getPublishedArticlesList();
    return articles.map((a) => ({ slug: a.slug }));
  } catch {
    return [];
  }
}

export async function generateMetadata({
  params,
}: {
  params: Promise<{ slug: string }>;
}): Promise<Metadata> {
  const { slug } = await params;
  const article = await getArticleBySlug(slug);
  if (!article) return {};

  const description = article.metaDescription || article.excerpt;

  return {
    title: article.title,
    description,
    // 未公開記事はDraft Mode経由でしか表示されない（＝クローラーは到達できない）が、
    // 念のためインデックス禁止を明示しておく
    ...(article.status !== "published"
      ? { robots: { index: false, follow: false } }
      : {}),
    alternates: {
      canonical: `/articles/${article.slug}`,
    },
    openGraph: {
      title: article.title,
      description,
      type: "article",
      publishedTime: article.publishedAt ?? undefined,
      modifiedTime: article.updatedAt,
      siteName: "Camp Gear Lab",
      locale: "ja_JP",
      url: `/articles/${article.slug}`,
      authors: ["ギア男（現役小児科開業医）"],
      tags: article.tags,
    },
    twitter: {
      card: "summary_large_image",
      title: article.title,
      description,
    },
  };
}

export default async function ArticlePage({
  params,
}: {
  params: Promise<{ slug: string }>;
}) {
  const { slug } = await params;
  const { isEnabled: isPreview } = await draftMode();
  const article = await getArticleBySlug(slug);
  if (!article) notFound();
  if (article.status !== "published" && !isPreview) notFound();

  const [categories, category, products, sameCategoryArticles, allArticles] =
    await Promise.all([
      getCategories(),
      getCategoryById(article.categoryId),
      getProductsByIds(article.productIds),
      getArticlesByCategory(article.categoryId),
      getPublishedArticlesList(),
    ]);
  // 共通商品数 × 10 − 経過日数 でスコアリング（productIds共通が最優先）
  // ISR(6h)ごとに再計算されるサーバーコンポーネントなので現在時刻の参照は安全
  // eslint-disable-next-line react-hooks/purity
  const renderedAt = Date.now();
  const scoreRelevance = (a: { productIds?: string[]; publishedAt?: string | null }) => {
    const shared = (a.productIds ?? []).filter((id) =>
      (article.productIds ?? []).includes(id)
    ).length;
    const daysSince =
      (renderedAt - new Date(a.publishedAt ?? 0).getTime()) / 86400000;
    return shared * 10 - Math.min(daysSince, 365);
  };

  const relatedArticles = sameCategoryArticles
    .filter((a) => a.id !== article.id)
    .sort((a, b) => scoreRelevance(b) - scoreRelevance(a))
    .slice(0, 3);

  const otherCategoryArticles = allArticles
    .filter(
      (a) =>
        a.status === "published" &&
        a.id !== article.id &&
        a.categoryId !== article.categoryId
    )
    .sort((a, b) => scoreRelevance(b) - scoreRelevance(a))
    .slice(0, 3);

  // 本文にFAQセクションが直書きされている記事が47本あり、システム生成FAQと
  // 二重表示になっていた。本文側を優先し、システムFAQ（表示とFAQPage JSON-LDの
  // 両方）を抑止する。JSON-LDだけ残すと「ページに見えている内容と構造化データの
  // 不一致」になるため両方消す
  const bodyHasFaq = /^##+ *よくある(ご)?質問/m.test(article.content);
  const faqs = bodyHasFaq ? [] : article.faqs ?? [];

  // 「医師から一言」セクションをまとめ直前に注入
  const medicalAdvice = MEDICAL_ADVICE_MAP[article.slug] ?? null;
  let contentBefore = article.content;
  let contentSummaryOnward: string | null = null;
  if (medicalAdvice) {
    const idx = article.content.indexOf("\n## まとめ");
    if (idx !== -1) {
      contentBefore = article.content.slice(0, idx);
      contentSummaryOnward = article.content.slice(idx + 1);
    }
  }
  const baseUrl = "https://camp-gear-lab.com";

  const articleJsonLd = {
    "@context": "https://schema.org",
    "@type": "Article",
    headline: article.title,
    description: article.excerpt,
    // Googleのリッチリザルトで推奨される image。記事のアイキャッチ or 掲載商品の
    // 画像を優先し、無ければ動的生成のOGP画像（1200x630）にフォールバックする
    image:
      article.eyecatch ||
      products.find((p) => p.imageUrl)?.imageUrl ||
      `${baseUrl}/articles/${article.slug}/opengraph-image`,
    datePublished: article.publishedAt,
    dateModified: article.updatedAt,
    author: {
      "@type": "Person",
      "@id": `${baseUrl}/about#person`,
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
    publisher: {
      "@type": "Organization",
      name: "Camp Gear Lab",
      url: baseUrl,
      logo: {
        "@type": "ImageObject",
        url: `${baseUrl}/logo.png`,
        width: 512,
        height: 512,
      },
    },
    mainEntityOfPage: `${baseUrl}/articles/${article.slug}`,
  };

  const breadcrumbJsonLd = {
    "@context": "https://schema.org",
    "@type": "BreadcrumbList",
    itemListElement: [
      { "@type": "ListItem", position: 1, name: "ホーム", item: baseUrl },
      ...(category
        ? [
            {
              "@type": "ListItem",
              position: 2,
              name: category.name,
              item: `${baseUrl}/category/${category.slug}`,
            },
            {
              "@type": "ListItem",
              position: 3,
              name: article.title,
            },
          ]
        : [{ "@type": "ListItem", position: 2, name: article.title }]),
    ],
  };

  const productJsonLd = products
    .filter((p) => p.price > 0)
    .map((p) => ({
      "@context": "https://schema.org",
      "@type": "Product",
      name: p.name,
      brand: { "@type": "Brand", name: p.brand },
      description: p.description,
      image: p.imageUrl || undefined,
      // 当サイトは販売者ではなく送客サイト。在庫・送料・配送日数・返品条件は
      // 販売店ごとに異なり事実確認もできないため出力しない（不正確な構造化
      // データはリッチリザルト除外・手動対策の原因になる）。価格とリンク先のみ
      offers: {
        "@type": "Offer",
        price: p.price,
        priceCurrency: "JPY",
        url: p.affiliateUrl || p.amazonUrl || undefined,
      },
    }));

  const faqJsonLd =
    faqs.length > 0
      ? {
          "@context": "https://schema.org",
          "@type": "FAQPage",
          mainEntity: faqs.map((faq) => ({
            "@type": "Question",
            name: faq.question,
            acceptedAnswer: {
              "@type": "Answer",
              text: faq.answer,
            },
          })),
        }
      : null;

  // 記事内の {{youtube:ID|キャプション|YYYY-MM-DD}} から VideoObject を生成する。
  // GoogleのVideoObjectは uploadDate（動画の公開日）が必須のため、
  // 日付付きタグのみ対象（日付なしの埋め込みは表示のみでスキーマは出さない）。
  const videoJsonLd = [
    ...(article.content || "").matchAll(
      /\{\{youtube:([A-Za-z0-9_-]{6,20})\|([^|}]+)\|(\d{4}-\d{2}-\d{2})\}\}/g
    ),
  ].map((m) => ({
    "@context": "https://schema.org",
    "@type": "VideoObject",
    name: m[2].trim(),
    description: `${m[2].trim()}｜${article.title}`,
    thumbnailUrl: `https://i.ytimg.com/vi/${m[1]}/hqdefault.jpg`,
    uploadDate: m[3],
    embedUrl: `https://www.youtube-nocookie.com/embed/${m[1]}`,
  }));

  return (
    <>
      <script
        type="application/ld+json"
        dangerouslySetInnerHTML={{
          __html: toJsonLd(articleJsonLd),
        }}
      />
      <script
        type="application/ld+json"
        dangerouslySetInnerHTML={{
          __html: toJsonLd(breadcrumbJsonLd),
        }}
      />
      {faqJsonLd && (
        <script
          type="application/ld+json"
          dangerouslySetInnerHTML={{
            __html: toJsonLd(faqJsonLd),
          }}
        />
      )}
      {productJsonLd.map((pld, i) => (
        <script
          key={i}
          type="application/ld+json"
          dangerouslySetInnerHTML={{
            __html: toJsonLd(pld),
          }}
        />
      ))}
      {videoJsonLd.map((vld, i) => (
        <script
          key={`video-${i}`}
          type="application/ld+json"
          dangerouslySetInnerHTML={{
            __html: toJsonLd(vld),
          }}
        />
      ))}
      <Header categories={categories} />
      <main className="flex-1">
        <article className="max-w-4xl mx-auto px-4 py-12">
          {/* Breadcrumb */}
          <nav className="text-sm text-slate-500 mb-6" aria-label="パンくず">
            <Link href="/" className="hover:text-lake-600 transition">
              ホーム
            </Link>
            {category && (
              <>
                <span className="mx-2 text-slate-400">/</span>
                <Link
                  href={`/category/${category.slug}`}
                  className="hover:text-lake-600 transition"
                >
                  {category.name}
                </Link>
              </>
            )}
          </nav>

          <HeroImage article={article} products={products} />

          <h1 className="text-3xl md:text-4xl font-semibold tracking-tight text-ink-strong leading-tight mb-5">
            {article.title}
          </h1>

          <div className="flex flex-wrap items-center gap-x-4 gap-y-2 text-sm mb-10 pb-4 border-b border-line">
            <Link
              href="/about"
              className="inline-flex items-center gap-1.5 text-slate-600 hover:text-lake-600 transition"
            >
              <span>🩺</span>
              <span className="font-medium">ギア男（現役小児科開業医）</span>
              <span className="text-slate-400">監修・執筆</span>
            </Link>
            {(article.updatedAt ?? article.publishedAt) && (
              <time className="text-slate-500">
                最終更新:{" "}
                {new Date(
                  article.updatedAt ?? article.publishedAt ?? ""
                ).toLocaleDateString("ja-JP", {
                  year: "numeric",
                  month: "long",
                  day: "numeric",
                })}
              </time>
            )}
            {category && (
              <Link
                href={`/category/${category.slug}`}
                className="bg-lake-50 text-lake-700 hover:bg-lake-100 border border-lake-100 px-3 py-1 rounded-full text-xs font-medium transition"
              >
                {category.name}
              </Link>
            )}
          </div>

          {/* 楽天の買い時バナー（5と0のつく日・セール期間に自動表示） */}
          {products.some((p) => p.affiliateUrl) && <RakutenDealBadge />}

          {/* 記事冒頭 購入導線（広告表示は導線より前に置く＝ステマ規制対応） */}
          {products.length > 0 && (
            <>
              <AffiliateDisclosure variant="inline" />
              <RecommendationCTA products={products.slice(0, 3)} />
            </>
          )}

          {/* Article body */}
          {contentSummaryOnward ? (
            <>
              <ArticleContent content={contentBefore} products={products} />
              <MedicalAdvice {...medicalAdvice!} />
              <ArticleContent content={contentSummaryOnward} products={products} />
            </>
          ) : (
            <ArticleContent content={article.content} products={products} />
          )}

          {/* 記事末尾 購入導線（読了直後が最も購買意欲が高い） */}
          {products.length > 0 && (
            <RecommendationCTA
              products={products.slice(0, 3)}
              title={`この記事で紹介した${Math.min(products.length, 3)}つ`}
              subtitle="気になるモデルがあれば、在庫と価格をチェックしてみてください"
              placement="article_end"
            />
          )}
        </article>

        {/* FAQ section */}
        {faqs.length > 0 && (
          <section className="max-w-4xl mx-auto px-4 pb-12">
            <h2 className="text-2xl font-semibold text-ink-strong tracking-tight mb-6">
              よくある質問
            </h2>
            <div className="space-y-3">
              {faqs.map((faq, i) => (
                <details
                  key={i}
                  className="bg-white rounded-xl border border-line overflow-hidden group hover:border-lake-200 transition"
                >
                  <summary className="cursor-pointer px-5 py-4 font-medium text-ink-strong hover:bg-lake-50/40 transition flex items-center justify-between list-none">
                    <span>Q. {faq.question}</span>
                    <span className="text-lake-600 group-open:rotate-180 transition-transform ml-2 text-sm">
                      ▼
                    </span>
                  </summary>
                  <div className="px-5 pb-5 text-slate-700 leading-relaxed border-t border-line-soft pt-4">
                    {faq.answer}
                  </div>
                </details>
              ))}
            </div>
          </section>
        )}

        {/* Related articles */}
        {relatedArticles.length > 0 && (
          <section className="max-w-4xl mx-auto px-4 pb-12">
            <h2 className="text-xl font-semibold text-ink-strong tracking-tight mb-6">
              関連する記事
            </h2>
            <div className="grid sm:grid-cols-3 gap-4">
              {relatedArticles.map((a) => (
                <Link
                  key={a.id}
                  href={`/articles/${a.slug}`}
                  className="bg-white rounded-xl transition p-4 border border-line hover:border-lake-200 hover:bg-lake-50/30 group"
                >
                  <h3 className="font-semibold text-ink-strong text-sm mb-1 line-clamp-2 leading-snug group-hover:text-lake-700 transition">
                    {a.title}
                  </h3>
                  <p className="text-xs text-slate-500 line-clamp-2 leading-relaxed">
                    {a.excerpt}
                  </p>
                </Link>
              ))}
            </div>
          </section>
        )}
        {/* Other category articles */}
        {otherCategoryArticles.length > 0 && (
          <section className="max-w-4xl mx-auto px-4 pb-12">
            <h2 className="text-xl font-semibold text-ink-strong tracking-tight mb-6">
              他のカテゴリの人気記事
            </h2>
            <div className="grid sm:grid-cols-3 gap-4">
              {otherCategoryArticles.map((a) => {
                const cat = categories.find((c) => c.id === a.categoryId);
                return (
                  <Link
                    key={a.id}
                    href={`/articles/${a.slug}`}
                    className="bg-white rounded-xl transition p-4 border border-line hover:border-lake-200 hover:bg-lake-50/30 group"
                  >
                    {cat && (
                      <span className="inline-block text-xs text-lake-700 font-medium bg-lake-50 border border-lake-100 px-2 py-0.5 rounded-full mb-2">
                        {cat.name}
                      </span>
                    )}
                    <h3 className="font-semibold text-ink-strong text-sm mb-1 line-clamp-2 leading-snug group-hover:text-lake-700 transition">
                      {a.title}
                    </h3>
                    <p className="text-xs text-slate-500 line-clamp-2 leading-relaxed">
                      {a.excerpt}
                    </p>
                  </Link>
                );
              })}
            </div>
          </section>
        )}

        {/* PR表記（ページ最下部） */}
        <div className="max-w-4xl mx-auto px-4 pb-10">
          <AffiliateDisclosure />
        </div>
      </main>
      <Footer categories={categories} />
    </>
  );
}
