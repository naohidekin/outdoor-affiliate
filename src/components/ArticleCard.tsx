import Image from "next/image";
import Link from "next/link";
import { getCategoryIcon } from "@/lib/category-icons";
import { sizedImageUrl } from "@/lib/imageSize";
import { Article, Category, Product } from "@/lib/types";
import { getArticleLabel } from "@/lib/articleEditorial";

interface Props {
  article: Article;
  category?: Category;
  thumbnailProduct?: Product;
}

export default function ArticleCard({ article, category, thumbnailProduct }: Props) {
  const thumbProduct = thumbnailProduct;
  const categorySlug = category?.slug ?? "";
  const fallbackIcon = getCategoryIcon(categorySlug, "xl", 1.5);

  return (
    <Link
      href={`/articles/${article.slug}`}
      className="group block bg-white rounded-xl border border-line hover:border-lake-200 hover:bg-lake-50/20 transition overflow-hidden"
    >
      {/* Thumbnail */}
      <div className="relative aspect-[16/10] bg-mist border-b border-line-soft overflow-hidden">
        {article.eyecatch || thumbProduct?.imageUrl ? (
          <Image
            src={sizedImageUrl(article.eyecatch || thumbProduct!.imageUrl, 640)}
            alt={article.title}
            fill
            sizes="(max-width: 640px) 100vw, (max-width: 1024px) 50vw, 33vw"
            className={`${article.eyecatch ? "object-cover" : "object-contain p-6 bg-white"} transition-transform duration-500 motion-reduce:transition-none group-hover:scale-[1.03]`}
            loading="lazy"
          />
        ) : (
          <div className="absolute inset-0 flex items-center justify-center bg-gradient-to-br from-lake-50 to-mist text-lake-300">
            {fallbackIcon}
          </div>
        )}
        <span className="absolute left-4 top-4 rounded-full bg-white/95 px-3 py-1 text-xs font-medium text-ink border border-line-soft">{getArticleLabel(article)}</span>
      </div>

      {/* Content */}
      <div className="p-5">
        {category && (
          <div className="flex items-center gap-1.5 mb-2">
            <span className="text-lake-600">
              {getCategoryIcon(category.slug, "sm"
              )}
            </span>
            <span className="text-xs font-medium text-slate-500 tracking-wide">
              {category.name}
            </span>
          </div>
        )}
        <h3 className="font-semibold text-ink-strong text-base leading-relaxed mb-2 line-clamp-3 group-hover:text-lake-700 transition">
          {article.title}
        </h3>
        <p className="text-sm text-slate-500 line-clamp-2 leading-relaxed">
          {article.excerpt}
        </p>
        {article.publishedAt && (
          <p className="text-xs text-slate-400 mt-3">
            {new Date(article.publishedAt).toLocaleDateString("ja-JP")}
          </p>
        )}
      </div>
    </Link>
  );
}
