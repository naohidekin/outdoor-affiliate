import type { Metadata } from "next";
import Link from "next/link";
import { notFound } from "next/navigation";
import {
  getCategories,
  getArticles,
  getArticleBySlug,
  getProductsByIds,
  getCategoryById,
  getArticlesByCategory,
} from "@/lib/db";
import Header from "@/components/Header";
import Footer from "@/components/Footer";
import ArticleContent from "@/components/ArticleContent";
import MedicalAdvice from "@/components/MedicalAdvice";
import { MEDICAL_ADVICE_MAP } from "@/lib/medicalAdviceData";

export const revalidate = 3600; // ISR: 1時間

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
    alternates: {
      canonical: `/articles/${article.slug}`,
    },
    openGraph: {
      title: article.title,
      description,
      type: "article",
      publishedTime: article.publishedAt ?? undefined,
      modifiedTime: article.updatedAt,
      siteName: "Outdoor Gear Lab",
      locale: "ja_JP",
      url: `/articles/${article.slug}`,
    },
    twitter: {
      card: "summary_large_image",
      title: article.title,
      description: article.excerpt,
    },
  };
}

export default async function ArticlePage({
  params,
  searchParams,
}: {
  params: Promise<{ slug: string }>;
  searchParams?: Promise<{ preview?: string }>;
}) {
  const { slug } = await params;
  const sp = searchParams ? await searchParams : {};
  const isPreview = sp?.preview === "1";
  const article = await getArticleBySlug(slug);
  if (!article) notFound();
  if (article.status !== "published" && !isPreview) notFound();

  const [categories, category, products, sameCategoryArticles, allArticles] =
    await Promise.all([
      getCategories(),
      getCategoryById(article.categoryId),
      getProductsByIds(article.productIds),
      getArticlesByCategory(article.categoryId),
      getArticles(),
    ]);
  // 共通商品数 × 10 − 経過日数 でスコアリング（productIds共通が最優先）
  const scoreRelevance = (a: { productIds?: string[]; publishedAt?: string | null }) => {
    const shared = (a.productIds ?? []).filter((id) =>
      (article.productIds ?? []).includes(id)
    ).length;
    const daysSince =
      (Date.now() - new Date(a.publishedAt ?? 0).getTime()) / 86400000;
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

  const faqs = article.faqs ?? [];

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
    datePublished: article.publishedAt,
    dateModified: article.updatedAt,
    author: {
      "@type": "Person",
      name: "現役小児科開業医",
      jobTitle: "小児科医",
      description: "現役の小児科開業医。キャンプ歴10年、2児の父。医師目線で家族が安全に楽しめるアウトドアギアを比較・検証。",
      url: `${baseUrl}/about`,
      sameAs: [
        "https://twitter.com/camp_gear_lab",
        `${baseUrl}/about`,
      ],
    },
    publisher: {
      "@type": "Organization",
      name: "Outdoor Gear Lab",
      url: baseUrl,
      logo: {
        "@type": "ImageObject",
        url: `${baseUrl}/favicon.ico`,
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
      ...(p.rating > 0 && {
        aggregateRating: {
          "@type": "AggregateRating",
          ratingValue: p.rating,
          bestRating: 5,
          ratingCount: 1,
        },
      }),
      offers: {
        "@type": "Offer",
        price: p.price,
        priceCurrency: "JPY",
        availability: "https://schema.org/InStock",
        url: p.affiliateUrl || p.amazonUrl || undefined,
        shippingDetails: {
          "@type": "OfferShippingDetails",
          shippingDestination: {
            "@type": "DefinedRegion",
            addressCountry: "JP",
          },
          deliveryTime: {
            "@type": "ShippingDeliveryTime",
            handlingTime: { "@type": "QuantitativeValue", minValue: 1, maxValue: 3, unitCode: "d" },
            transitTime: { "@type": "QuantitativeValue", minValue: 1, maxValue: 5, unitCode: "d" },
          },
          shippingRate: {
            "@type": "MonetaryAmount",
            value: 0,
            currency: "JPY",
          },
        },
        hasMerchantReturnPolicy: {
          "@type": "MerchantReturnPolicy",
          applicableCountry: "JP",
          returnPolicyCategory: "https://schema.org/MerchantReturnNotPermitted",
        },
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

  const isHowToArticle = /選び方|ガイド|完全/.test(article.title);
  const howToJsonLd = isHowToArticle
    ? (() => {
        const headingRegex = /^##\s+(.+)$/gm;
        const steps: { "@type": string; name: string; text: string }[] = [];
        let match;
        while ((match = headingRegex.exec(article.content)) !== null) {
          const heading = match[1].replace(/[#*]/g, "").trim();
          if (
            heading &&
            !heading.startsWith("合わせて読みたい") &&
            !heading.startsWith("まとめ") &&
            !heading.startsWith("よくある質問")
          ) {
            steps.push({
              "@type": "HowToStep",
              name: heading,
              text: heading,
            });
          }
        }
        return steps.length >= 2
          ? {
              "@context": "https://schema.org",
              "@type": "HowTo",
              name: article.title,
              description: article.metaDescription || article.excerpt,
              step: steps.slice(0, 8),
            }
          : null;
      })()
    : null;

  return (
    <>
      <script
        type="application/ld+json"
        dangerouslySetInnerHTML={{
          __html: JSON.stringify(articleJsonLd),
        }}
      />
      <script
        type="application/ld+json"
        dangerouslySetInnerHTML={{
          __html: JSON.stringify(breadcrumbJsonLd),
        }}
      />
      {faqJsonLd && (
        <script
          type="application/ld+json"
          dangerouslySetInnerHTML={{
            __html: JSON.stringify(faqJsonLd),
          }}
        />
      )}
      {howToJsonLd && (
        <script
          type="application/ld+json"
          dangerouslySetInnerHTML={{
            __html: JSON.stringify(howToJsonLd),
          }}
        />
      )}
      {productJsonLd.map((pld, i) => (
        <script
          key={i}
          type="application/ld+json"
          dangerouslySetInnerHTML={{
            __html: JSON.stringify(pld),
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

          <h1 className="text-3xl md:text-4xl font-semibold tracking-tight text-ink-strong leading-tight mb-5">
            {article.title}
          </h1>

          <div className="flex flex-wrap items-center gap-x-4 gap-y-2 text-sm mb-10 pb-4 border-b border-line">
            <Link
              href="/about"
              className="inline-flex items-center gap-1.5 text-slate-600 hover:text-lake-600 transition"
            >
              <span>🩺</span>
              <span className="font-medium">現役小児科開業医</span>
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
      </main>
      <Footer categories={categories} />
    </>
  );
}
