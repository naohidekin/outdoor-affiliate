import type { Metadata } from "next";
import Link from "next/link";
import { ArrowRight, Check } from "lucide-react";
import Header from "@/components/Header";
import Footer from "@/components/Footer";
import GearGuideTopics from "@/components/GearGuideTopics";
import GuideLink from "@/components/GuideLink";
import { getPublicCategories, getPublishedArticlesList } from "@/lib/db";
import { getAvailableGearGuides } from "@/lib/gearGuides";
import { toJsonLd } from "@/lib/jsonld";

export const revalidate = 21600;
export const metadata: Metadata = {
  title: "家族のキャンプ道具を目的から選ぶ｜寝具・テント・ランタン・暑さ対策",
  description: "家族の寝具、テントの広さ、夜の明かり、暑い日の装備。購入前に確認する条件と、次に読む比較記事を目的別にまとめました。",
  alternates: { canonical: "/gear-guides" },
};

export default async function GearGuidesPage() {
  const [categories, articles] = await Promise.all([getPublicCategories(), getPublishedArticlesList()]);
  const guides = getAvailableGearGuides(articles);
  const linkedArticles = [...new Map(guides.flatMap((guide) => guide.links).map((link) => [link.slug, link])).values()];
  return <>
    <Header categories={categories} />
    <main className="flex-1">
      <div className="max-w-5xl mx-auto px-4 sm:px-6 pt-6 pb-12">
        <nav aria-label="パンくず" className="text-sm text-slate-500 mb-6"><Link href="/" className="hover:underline">ホーム</Link><span className="mx-2">/</span>目的からギアを選ぶ</nav>
        <div className="grid md:grid-cols-2 gap-6 md:gap-12 items-center border-b border-line pb-8">
          <div>
            <p className="text-sm text-lake-600 font-medium mb-3">家族のキャンプ道具選び</p>
            <h1 className="text-3xl sm:text-4xl font-semibold leading-[1.45] tracking-tight text-ink-strong">何を買うかの前に、<br />何に困っているか。</h1>
            <p className="mt-4 text-base leading-loose text-slate-600">寝床が狭い。設営に時間がかかる。夜の手元が暗い。気になることから、必要な道具と選び方を探せます。</p>
          </div>
          <GearGuideTopics guides={guides} placement="guide" />
        </div>
        {guides.map((guide, index) => <section key={guide.id} id={guide.id} aria-labelledby={`${guide.id}-title`} className="scroll-mt-24 py-9 md:py-12 border-b border-line">
          <div className="flex gap-4 items-start mb-6">
            <span className="text-sm font-semibold tabular-nums text-lake-600 border-t-2 border-lake-600 pt-2" aria-hidden="true">{String(index + 1).padStart(2, "0")}</span>
            <div><h2 id={`${guide.id}-title`} className="text-2xl font-semibold text-ink-strong">{guide.label}</h2><p className="mt-2 text-base leading-relaxed text-slate-600">{guide.description}</p></div>
          </div>
          <div className="grid md:grid-cols-[1fr_1.8fr] gap-5 md:gap-8">
            <div className="rounded-xl bg-mist p-5 self-start">
              <h3 className="text-base font-semibold text-ink-strong mb-3">買う前に確認すること</h3>
              <ul className="space-y-3">{guide.checks.map((check) => <li key={check} className="flex gap-2 text-sm text-slate-600 leading-relaxed"><Check size={17} className="mt-0.5 shrink-0 text-lake-600" aria-hidden="true" />{check}</li>)}</ul>
            </div>
            <div className="divide-y divide-line border-y border-line">
              {guide.links.map((link) => <GuideLink key={link.slug} guideId={guide.id} placement="guide" href={`/articles/${link.slug}`} className="group flex items-center gap-4 py-5">
                <div className="min-w-0"><h3 className="text-base font-semibold leading-relaxed text-ink-strong group-hover:text-lake-700">{link.label}</h3><p className="mt-1 text-sm leading-relaxed text-slate-500">{link.detail}</p></div><ArrowRight size={18} aria-hidden="true" className="ml-auto shrink-0 text-lake-600" />
              </GuideLink>)}
            </div>
          </div>
        </section>)}
        <div className="mt-8 flex flex-wrap gap-4 justify-between text-sm">
          <Link href="/articles" className="min-h-11 inline-flex items-center font-semibold text-lake-600 hover:underline">商品名・カテゴリから記事を探す →</Link>
          <Link href="/about" className="min-h-11 inline-flex items-center text-slate-600 hover:underline">書き手と編集方針</Link>
        </div>
      </div>
    </main>
    <script type="application/ld+json" dangerouslySetInnerHTML={{ __html: toJsonLd({
      "@context": "https://schema.org", "@type": "CollectionPage", name: "家族のキャンプ道具を目的から選ぶ", url: "https://camp-gear-lab.com/gear-guides",
      mainEntity: { "@type": "ItemList", itemListElement: linkedArticles.map((link, index) => ({ "@type": "ListItem", position: index + 1, name: link.articleTitle, url: `https://camp-gear-lab.com/articles/${link.slug}` })) },
    }) }} />
    <Footer categories={categories} />
  </>;
}
