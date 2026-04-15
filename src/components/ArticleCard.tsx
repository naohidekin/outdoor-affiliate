import Image from "next/image";
import Link from "next/link";
import { getCategoryIcon } from "@/lib/category-icons";
import { Article, Category, Product } from "@/lib/types";

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
        {thumbProduct ? (
          <Image
            src={thumbProduct.imageUrl}
            alt={article.title}
            fill
            sizes="(max-width: 640px) 100vw, (max-width: 1024px) 50vw, 33vw"
            className="object-cover transition-transform duration-500 group-hover:scale-105"
            loading="lazy"
          />
        ) : (
          <div className="absolute inset-0 flex items-center justify-center bg-gradient-to-br from-lake-50 to-mist text-lake-300">
            {fallbackIcon}
          </div>
        )}
        {/* Top accent line */}
        <div className="absolute top-0 left-0 right-0 h-0.5 bg-lake-600/70" />
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
        <h3 className="font-semibold text-ink-strong text-[15px] leading-snug mb-2 line-clamp-2 group-hover:text-lake-700 transition">
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
