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

export const dynamic = "force-dynamic";

export async function generateMetadata({
  params,
}: {
  params: Promise<{ slug: string }>;
}): Promise<Metadata> {
  const { slug } = await params;
  const article = getArticleBySlug(slug);
  if (!article) return {};

  return {
    title: article.title,
    description: article.excerpt,
    alternates: {
      canonical: `/articles/${article.slug}`,
    },
    openGraph: {
      title: article.title,
      description: article.excerpt,
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
}: {
  params: Promise<{ slug: string }>;
}) {
  const { slug } = await params;
  const article = getArticleBySlug(slug);
  if (!article || article.status !== "published") notFound();

  const categories = getCategories();
  const category = getCategoryById(article.categoryId);
  const products = getProductsByIds(article.productIds);
  const relatedArticles = category
    ? getArticlesByCategory(category.id)
        .filter((a) => a.id !== article.id)
        .slice(0, 3)
    : [];

  const allPublished = getArticles().filter(
    (a) =>
      a.status === "published" &&
      a.id !== article.id &&
      a.categoryId !== article.categoryId
  );
  const otherCategoryArticles = allPublished.slice(0, 3);

  const faqs = article.faqs ?? [];
  const baseUrl = "https://camp-gear-lab.com";

  const articleJsonLd = {
    "@context": "https://schema.org",
    "@type": "Article",
    headline: article.title,
    description: article.excerpt,
    datePublished: article.publishedAt,
    dateModified: article.updatedAt,
    author: { "@type": "Organization", name: "Outdoor Gear Lab" },
    publisher: {
      "@type": "Organization",
      name: "Outdoor Gear Lab",
      url: baseUrl,
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
          <nav className="text-sm text-gray-400 mb-6">
            <Link href="/" className="hover:text-green-600">
              ホーム
            </Link>
            {category && (
              <>
                {" / "}
                <Link
                  href={`/category/${category.slug}`}
                  className="hover:text-green-600"
                >
                  {category.name}
                </Link>
              </>
            )}
          </nav>

          <h1 className="text-3xl md:text-4xl font-bold text-gray-800 mb-4">
            {article.title}
          </h1>

          <div className="flex items-center gap-4 text-sm text-amber-700 mb-8">
            {article.publishedAt && (
              <time>
                {new Date(article.publishedAt).toLocaleDateString("ja-JP", {
                  year: "numeric",
                  month: "long",
                  day: "numeric",
                })}
              </time>
            )}
            {category && (
              <Link
                href={`/category/${category.slug}`}
                className="bg-amber-100 text-amber-800 px-3 py-1 rounded-full text-xs font-medium"
              >
                {category.name}
              </Link>
            )}
          </div>

          {/* Article body */}
          <ArticleContent content={article.content} products={products} />
        </article>

        {/* FAQ section */}
        {faqs.length > 0 && (
          <section className="max-w-4xl mx-auto px-4 pb-12">
            <h2 className="text-2xl font-bold text-amber-900 mb-6">
              よくある質問
            </h2>
            <div className="space-y-4">
              {faqs.map((faq, i) => (
                <details
                  key={i}
                  className="bg-white rounded-xl border border-amber-200 overflow-hidden group"
                >
                  <summary className="cursor-pointer px-6 py-4 font-semibold text-gray-800 hover:bg-amber-50 transition flex items-center justify-between">
                    <span>Q. {faq.question}</span>
                    <span className="text-amber-600 group-open:rotate-180 transition-transform ml-2">
                      ▼
                    </span>
                  </summary>
                  <div className="px-6 pb-4 text-gray-700 leading-relaxed border-t border-amber-100 pt-4">
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
            <h2 className="text-xl font-bold text-amber-900 mb-6">
              関連する記事
            </h2>
            <div className="grid sm:grid-cols-3 gap-4">
              {relatedArticles.map((a) => (
                <Link
                  key={a.id}
                  href={`/articles/${a.slug}`}
                  className="bg-white rounded-xl shadow-sm hover:shadow-md transition p-4 border border-amber-100 hover:border-amber-300"
                >
                  <h3 className="font-semibold text-gray-800 text-sm mb-1 line-clamp-2">
                    {a.title}
                  </h3>
                  <p className="text-xs text-gray-500 line-clamp-2">
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
            <h2 className="text-xl font-bold text-amber-900 mb-6">
              他のカテゴリの人気記事
            </h2>
            <div className="grid sm:grid-cols-3 gap-4">
              {otherCategoryArticles.map((a) => {
                const cat = getCategoryById(a.categoryId);
                return (
                  <Link
                    key={a.id}
                    href={`/articles/${a.slug}`}
                    className="bg-white rounded-xl shadow-sm hover:shadow-md transition p-4 border border-amber-100 hover:border-amber-300"
                  >
                    {cat && (
                      <span className="inline-block text-xs text-amber-700 font-semibold bg-amber-100 px-2 py-0.5 rounded-full mb-2">
                        {cat.name}
                      </span>
                    )}
                    <h3 className="font-semibold text-gray-800 text-sm mb-1 line-clamp-2">
                      {a.title}
                    </h3>
                    <p className="text-xs text-gray-500 line-clamp-2">
                      {a.excerpt}
                    </p>
                  </Link>
                );
              })}
            </div>
          </section>
        )}
      </main>
      <Footer />
    </>
  );
}
