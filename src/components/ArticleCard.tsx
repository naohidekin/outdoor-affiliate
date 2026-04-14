import Image from "next/image";
import Link from "next/link";
import {
  Tent,
  Lamp,
  Flame,
  Backpack,
  Snowflake,
  Mountain,
  Armchair,
  Table,
  ThermometerSnowflake,
  Shirt,
  Footprints,
  Cloudy,
} from "lucide-react";
import { Article, Category, Product } from "@/lib/types";

const CATEGORY_ICON: Record<string, React.ReactNode> = {
  tent: <Tent className="w-10 h-10" strokeWidth={1.5} />,
  lantern: <Lamp className="w-10 h-10" strokeWidth={1.5} />,
  burner: <Flame className="w-10 h-10" strokeWidth={1.5} />,
  backpack: <Backpack className="w-10 h-10" strokeWidth={1.5} />,
  "sleeping-bag": <Snowflake className="w-10 h-10" strokeWidth={1.5} />,
  shoes: <Footprints className="w-10 h-10" strokeWidth={1.5} />,
  chair: <Armchair className="w-10 h-10" strokeWidth={1.5} />,
  table: <Table className="w-10 h-10" strokeWidth={1.5} />,
  cooler: <ThermometerSnowflake className="w-10 h-10" strokeWidth={1.5} />,
  wear: <Shirt className="w-10 h-10" strokeWidth={1.5} />,
  firepit: <Flame className="w-10 h-10" strokeWidth={1.5} />,
  tarp: <Cloudy className="w-10 h-10" strokeWidth={1.5} />,
};

const CATEGORY_ICON_SMALL: Record<string, React.ReactNode> = {
  tent: <Tent className="w-3.5 h-3.5" />,
  lantern: <Lamp className="w-3.5 h-3.5" />,
  burner: <Flame className="w-3.5 h-3.5" />,
  backpack: <Backpack className="w-3.5 h-3.5" />,
  "sleeping-bag": <Snowflake className="w-3.5 h-3.5" />,
  shoes: <Footprints className="w-3.5 h-3.5" />,
  chair: <Armchair className="w-3.5 h-3.5" />,
  table: <Table className="w-3.5 h-3.5" />,
  cooler: <ThermometerSnowflake className="w-3.5 h-3.5" />,
  wear: <Shirt className="w-3.5 h-3.5" />,
  firepit: <Flame className="w-3.5 h-3.5" />,
  tarp: <Cloudy className="w-3.5 h-3.5" />,
};

interface Props {
  article: Article;
  category?: Category;
  thumbnailProduct?: Product;
}

export default function ArticleCard({ article, category, thumbnailProduct }: Props) {
  const thumbProduct = thumbnailProduct;
  const categorySlug = category?.slug ?? "";
  const fallbackIcon = CATEGORY_ICON[categorySlug] ?? (
    <Mountain className="w-10 h-10" strokeWidth={1.5} />
  );

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
              {CATEGORY_ICON_SMALL[category.slug] ?? (
                <Mountain className="w-3.5 h-3.5" />
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
