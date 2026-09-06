import { ArrowUpRight } from "lucide-react";
import type { NextRead } from "@/lib/articleNextReads";
import ArticleNavigationLink from "./ArticleNavigationLink";

export default function ArticleNextReads({ articleSlug, items }: { articleSlug: string; items: NextRead[] }) {
  if (items.length === 0) return null;
  return (
    <section aria-labelledby="next-reads-title" className="max-w-4xl mx-auto px-5 sm:px-6 pb-12">
      <div className="mb-5 border-t border-line pt-8">
        <h2 id="next-reads-title" className="text-xl font-semibold text-ink-strong tracking-tight">次に読む記事</h2>
        <p className="mt-2 text-sm text-slate-500">比較したあとも、家族に合う選び方を。</p>
      </div>
      <div className="grid gap-3 sm:grid-cols-3">
        {items.map(({ article, reason }) => (
          <ArticleNavigationLink key={article.slug} href={`/articles/${article.slug}`} articleSlug={articleSlug} destination="article" targetSlug={article.slug} area="next_reads" className="group flex flex-col rounded-xl border border-line bg-white p-5 hover:border-lake-300 hover:bg-lake-50/30 transition">
            <span className="text-sm font-medium text-lake-700">{reason}</span>
            <h3 className="mt-2 text-base font-semibold leading-relaxed text-ink-strong group-hover:text-lake-700">{article.title}</h3>
            <span className="mt-auto flex items-center gap-1 pt-4 text-sm text-slate-500">記事を読む<ArrowUpRight size={16} aria-hidden="true" /></span>
          </ArticleNavigationLink>
        ))}
      </div>
    </section>
  );
}
