import Image from "next/image";
import { Product } from "@/lib/types";
import AffiliateLink from "./AffiliateLink";
import RakutenDealStamp from "./RakutenDealStamp";

export default function RankingList({ products }: { products: Product[] }) {
  if (products.length === 0) return null;

  return (
    <div className="my-6 space-y-4">
      {products.map((product, i) => (
        <div
          key={product.id}
          className="relative bg-white rounded-xl border border-line p-5"
        >
          {product.affiliateUrl && <RakutenDealStamp />}
          {/* Header row: rank + image + (name on desktop) */}
          <div className="flex gap-4 items-start">
            <div className="flex-shrink-0">
              <div className="w-10 h-10 rounded-full flex items-center justify-center bg-lake-50 text-lake-700 border border-lake-100 font-semibold text-xs">
                {i + 1}位
              </div>
            </div>

            {product.imageUrl && (
              <div className="flex-shrink-0 w-20 h-20 sm:w-24 sm:h-24 rounded-lg overflow-hidden bg-mist relative">
                <Image
                  src={product.imageUrl}
                  alt={product.name}
                  fill
                  sizes="96px"
                  className="object-cover"
                  loading="lazy"
                />
              </div>
            )}

            <div className="flex-1 min-w-0">
              {product.brand && (
                <p className="text-xs text-slate-500 tracking-wide">{product.brand}</p>
              )}
              <h3 className="font-semibold text-ink-strong mb-1 leading-snug">{product.name}</h3>
              {product.rating > 0 && (
                <div className="text-amber-400 text-sm">
                  {"★".repeat(Math.floor(product.rating))}
                  {product.rating % 1 >= 0.5 ? "☆" : ""}
                  <span className="text-slate-500 ml-1">{product.rating}</span>
                </div>
              )}
              {product.price > 0 && (
                <span className="text-lg font-semibold text-lake-700 tracking-tight block mt-1">
                  ¥{product.price.toLocaleString()}
                </span>
              )}
            </div>
          </div>

          {/* Description */}
          {product.description && (
            <p className="text-sm text-slate-600 line-clamp-3 sm:line-clamp-2 leading-relaxed mt-3">
              {product.description}
            </p>
          )}

          {/* CTA row */}
          <div className="mt-4 flex flex-col sm:flex-row gap-2">
            {product.affiliateUrl && (
              <AffiliateLink
                href={product.affiliateUrl}
                productId={product.id}
                placement="ranking"
                productName={product.name}
                store="rakuten"
                className="inline-flex items-center justify-center px-4 py-2 rounded-lg text-sm font-medium text-white transition-colors whitespace-nowrap rakuten-btn"
              >
                楽天市場で見る
              </AffiliateLink>
            )}
            {product.amazonUrl && (
              <AffiliateLink
                href={product.amazonUrl}
                productId={product.id}
                placement="ranking"
                productName={product.name}
                store="amazon"
                className="inline-flex items-center justify-center px-4 py-2 rounded-lg text-sm font-medium transition-colors whitespace-nowrap amazon-btn"
              >
                Amazonで見る
              </AffiliateLink>
            )}
            {product.yahooUrl && (
              <AffiliateLink
                href={product.yahooUrl}
                productId={product.id}
                placement="ranking"
                productName={product.name}
                store="yahoo"
                className="inline-flex items-center justify-center px-4 py-2 rounded-lg text-sm font-medium border border-red-200 text-red-600 hover:bg-red-50 transition-colors whitespace-nowrap"
              >
                Yahoo!で見る
              </AffiliateLink>
            )}
            {product.affiliateUrl && (
              <AffiliateLink
                href={product.affiliateUrl}
                productId={product.id}
                placement="ranking"
                productName={product.name}
                store="rakuten"
                className="inline-flex items-center justify-center text-xs text-slate-500 hover:text-lake-600 underline underline-offset-2 transition-colors whitespace-nowrap sm:ml-1"
              >
                楽天で口コミをもっと見る →
              </AffiliateLink>
            )}
          </div>
        </div>
      ))}
    </div>
  );
}
