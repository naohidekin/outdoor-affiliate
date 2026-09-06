import type { Metadata } from "next";
import { toJsonLd } from "@/lib/jsonld";
import Link from "next/link";
import { draftMode } from "next/headers";
import { notFound } from "next/navigation";
import {
  getPublicCategories,
  getPublishedArticlesList,
  getArticleBySlug,
  getProductsByIds,
  getTrackingProducts,
  getCategoryById,
} from "@/lib/db";
import GuideLink from "@/components/GuideLink";
import { getAvailableGearGuides } from "@/lib/gearGuides";
import Header from "@/components/Header";
import Footer from "@/components/Footer";
import ArticleContent from "@/components/ArticleContent";
import MedicalAdvice from "@/components/MedicalAdvice";
import RecommendationCTA from "@/components/RecommendationCTA";
import RankingList from "@/components/RankingList";
import { getEditorialPicks, getPrimaryProducts } from "@/lib/articleEditorial";
import AffiliateDisclosure from "@/components/AffiliateDisclosure";
import { MEDICAL_ADVICE_MAP } from "@/lib/medicalAdviceData";
import HeroImage from "@/components/HeroImage";
import RakutenDealBadge from "@/components/RakutenDealBadge";
import { showTopCta } from "@/lib/articleCta";
import { extractToc } from "@/lib/toc";
import { sizedImageUrl } from "@/lib/imageSize";
import {
  extractFaqsFromContent,
  FAQ_HEADING_RE,
} from "@/lib/faq-from-content";
import TableOfContents from "@/components/TableOfContents";
import ArticleReadingNav from "@/components/ArticleReadingNav";
import ArticleNextReads from "@/components/ArticleNextReads";
import { getNextReads } from "@/lib/articleNextReads";
import { hasProductComparison } from "@/lib/articleNavigation";
import { detectAffiliateStore } from "@/lib/trackAffiliateClick";
import { ChevronDown, ShoppingBag } from "lucide-react";

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

  const [categories, category, products, allArticles, trackingProducts] = await Promise.all([
    getPublicCategories(),
    getCategoryById(article.categoryId),
    getProductsByIds(article.productIds),
    getPublishedArticlesList(),
    getTrackingProducts().catch(() => []), // Analytics lookup must not prevent article rendering.
  ]);
  const nextReads = getNextReads(article, allArticles);
  const gearGuide = getAvailableGearGuides(allArticles).find((guide) =>
    (guide.categoryIds as readonly string[]).includes(article.categoryId));
  const toc = extractToc(article.content);
  const primaryProducts = getPrimaryProducts(article, products).slice(0, 3);
  const editorialPicks = getEditorialPicks(article.slug, products);
  const hasTopProducts = showTopCta(article.slug) && primaryProducts.length > 0;
  const hasInlineAffiliate = (article.content.match(/https?:\/\/[^\s)<>]+/g) || []).some((href) => detectAffiliateStore(href));
  const hasComparison = hasProductComparison(article.content, products);

  // 本文にFAQセクションが直書きされている記事が47本あり、システム生成FAQと
  // 二重表示になっていた。本文側を優先し、システムFAQの「表示」を抑止する。
  //
  // 2026-08-26 変更。以前はここで JSON-LD も一緒に捨てていた。理由は
  // 「ページに見えている内容と構造化データの不一致」を避けるためで、判断自体は
  // 正しい。ただし結果として公開107本のうち47本（44%）から FAQPage が消えていた。
  // 不一致を無くす方向を変え、本文のFAQセクションから拾って出すようにする。
  // こうすると JSON-LD は定義上まさに画面に見えている内容そのものになる。
  const bodyHasFaq = FAQ_HEADING_RE.test(article.content);
  const faqs = bodyHasFaq ? [] : article.faqs ?? [];
  // 表示は本文がそのまま担当するので、これは JSON-LD 専用
  const faqsForJsonLd = bodyHasFaq
    ? extractFaqsFromContent(article.content)
    : faqs;

  // 「医師から一言」セクションをまとめ直前に注入
  //
  // 2026-08-26 修正。以前は "\n## まとめ" が見つからないと
  // contentSummaryOnward が null のままになり、描画側（下の
  // {contentSummaryOnward ? ...}）が丸ごと通常表示に落ちるため、
  // 医師アドバイスが1文字も出なかった。oniyamma-shinrinka-review が
  // まさにこれで、登録されているのに一度も表示されていなかった。
  // 安全に関する内容が、記事の書き方ひとつで静かに消えるのは筋が悪い。
  // まとめが無ければ「関連記事」の前、それも無ければ本文末尾に置く。
  const medicalAdvice = MEDICAL_ADVICE_MAP[article.slug] ?? null;
  let contentBefore = article.content;
  let contentSummaryOnward: string | null = null;
  if (medicalAdvice) {
    const anchors = ["\n## まとめ", "\n## 関連記事", "\n## よくある質問"];
    const idx = anchors
      .map((a) => article.content.indexOf(a))
      .filter((i) => i !== -1)
      .sort((a, b) => a - b)[0];
    if (idx !== undefined) {
      contentBefore = article.content.slice(0, idx);
      contentSummaryOnward = article.content.slice(idx + 1);
    } else {
      // 見出しが何も無い記事。末尾に置く（空文字だと描画側が落ちるので半角空白）
      contentSummaryOnward = " ";
    }
  }
  const comparisonBeforeSummary = hasProductComparison(contentBefore, products);
  const baseUrl = "https://camp-gear-lab.com";

  const articleJsonLd = {
    "@context": "https://schema.org",
    "@type": "Article",
    headline: article.title,
    description: article.excerpt,
    // Googleのリッチリザルトで推奨される image。記事のアイキャッチ or 掲載商品の
    // 画像を優先し、無ければ動的生成のOGP画像（1200x630）にフォールバックする。
    //
    // 2026-08-26 修正。ここだけ生の保存URLを使っていた。products.json には
    // ?_ex=128x128 のような小さいサイズ指定を含むURLが39件あり、表示側は
    // sizedImageUrl でその都度サイズを指定し直す（ProductCardは800px、
    // HeroPhotoは1200px）ので画面は問題なかったが、構造化データだけが
    // 128x128 を指していた。冬の主力記事 winter-camp-heating-comparison が
    // まさにこれで、Googleが画像付きリッチリザルトの対象外にする大きさだった。
    // 表示側と同じヘルパーを通して1200pxを要求する。
    image:
      sizedImageUrl(
        article.eyecatch || products.find((p) => p.imageUrl)?.imageUrl || "",
        1200
      ) || `${baseUrl}/articles/${article.slug}/opengraph-image`,
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
      // Article の image と同じ理由で、保存URLそのままではなくサイズを指定し直す
      image: p.imageUrl ? sizedImageUrl(p.imageUrl, 1200) : undefined,
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
    faqsForJsonLd.length > 0
      ? {
          "@context": "https://schema.org",
          "@type": "FAQPage",
          mainEntity: faqsForJsonLd.map((faq) => ({
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
        <article className="article-page max-w-4xl mx-auto px-5 sm:px-6 pt-6 sm:pt-10 pb-12">
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

          <h1 className="article-title text-[1.625rem] sm:text-3xl md:text-4xl font-semibold tracking-tight text-ink-strong leading-[1.5] mb-4">
            {article.title}
          </h1>

          <div className="flex flex-wrap items-center gap-x-4 gap-y-2 text-sm mb-5 pb-4 border-b border-line">
            <Link
              href="/about"
              className="inline-flex items-center gap-1.5 text-slate-600 hover:text-lake-600 transition"
            >
              <span aria-hidden="true">🩺</span>
              <span className="font-medium">ギア男（現役小児科開業医）</span>
              <span className="text-xs text-slate-500">監修・執筆</span>
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

          <HeroImage article={article} products={products} />

          <ArticleReadingNav articleSlug={article.slug} hasToc={toc.length >= 4} hasComparison={hasComparison} hasProducts={hasTopProducts} />
          {toc.length >= 4 && <TableOfContents items={toc} />}

          {/* 広告表示は折りたたみの外に置き、本文より先に見えるようにする。 */}
          {(products.length > 0 || hasInlineAffiliate) && <AffiliateDisclosure variant="inline" />}
          {hasTopProducts && (
            <details id="article-shopping" className="group mb-8 rounded-xl border border-lake-100 bg-lake-50/40 open:bg-white">
              <summary className="flex min-h-16 cursor-pointer list-none items-center gap-3 px-4 py-4 text-ink-strong">
                <ShoppingBag size={19} className="shrink-0 text-lake-600" aria-hidden="true" />
                <span className="text-base font-semibold">商品価格・選び方を確認</span>
                <ChevronDown size={18} className="ml-auto shrink-0 text-lake-600 transition-transform group-open:rotate-180" aria-hidden="true" />
              </summary>
              <div className="px-3 sm:px-5 pb-1 border-t border-lake-100">
                {primaryProducts.some((p) => p.affiliateUrl) && <RakutenDealBadge />}
                <RecommendationCTA products={primaryProducts} picks={editorialPicks} />
              </div>
            </details>
          )}

          <div id="article-reading-content" tabIndex={-1}>
            {contentSummaryOnward ? (
              <>
                <ArticleContent content={contentBefore} products={products} trackingProducts={trackingProducts} showProductFallback={false} comparisonAnchor={comparisonBeforeSummary} />
                <MedicalAdvice {...medicalAdvice!} />
                <ArticleContent content={contentSummaryOnward} products={products} trackingProducts={trackingProducts} showProductFallback={false} comparisonAnchor={!comparisonBeforeSummary && hasComparison} />
              </>
            ) : (
              <ArticleContent content={article.content} products={products} trackingProducts={trackingProducts} showProductFallback={false} comparisonAnchor={hasComparison} />
            )}
          </div>

          {/* 商品タグのない記事も、順序を順位に変換せず一度だけ全商品を表示。 */}
          {products.length > 0 && (
            /\{\{(?:product|comparison|ranking):/.test(article.content) ? (
              <RecommendationCTA
                products={primaryProducts}
                picks={editorialPicks}
                placement="article_end"
              />
            ) : (
              <section className="mt-10" aria-label="この記事で紹介した製品">
                <h2 className="text-xl font-semibold text-ink-strong">この記事で紹介した製品</h2>
                <RankingList products={products} ranked={false} />
              </section>
            )
          )}
        </article>

        {/* FAQ section */}
        {faqs.length > 0 && (
          <section className="max-w-4xl mx-auto px-5 sm:px-6 pb-12">
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

        <ArticleNextReads articleSlug={article.slug} items={nextReads} />
        {gearGuide && <div className="max-w-4xl mx-auto px-5 sm:px-6 pb-10">
            <GuideLink href={`/gear-guides#${gearGuide.id}`} guideId={gearGuide.id} placement="article" className="flex flex-wrap items-center justify-between gap-3 rounded-xl bg-mist border border-line p-5">
              <span><span className="block text-sm text-slate-500 mb-1">関連する道具も、まとめて検討する</span><span className="text-base font-semibold text-ink-strong">{gearGuide.label}</span></span>
              <span className="text-sm font-semibold text-lake-600">選び方ガイドへ →</span>
            </GuideLink>
          </div>}

        {/* PR表記（ページ最下部） */}
        <div className="max-w-4xl mx-auto px-4 pb-10">
          <AffiliateDisclosure />
        </div>
      </main>
      <Footer categories={categories} />
    </>
  );
}
