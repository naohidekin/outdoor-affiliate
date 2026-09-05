import Image from "next/image";
import { Product } from "@/lib/types";
import { isAmazonPrimary } from "@/lib/affiliate-priority";
import { sizedImageUrl } from "@/lib/imageSize";
import AffiliateLink from "./AffiliateLink";
import RakutenDealStamp from "./RakutenDealStamp";

function AmazonButton({ product }: { product: Product }) {
  if (!product.amazonUrl) return null;
  return (
    <AffiliateLink
      href={product.amazonUrl}
      productId={product.id}
      placement="ranking"
      productName={product.name}
      price={product.price}
      rank={isAmazonPrimary(product) ? 1 : 2}
      store="amazon"
      className="inline-flex items-center justify-center min-h-11 px-4 py-3 rounded-lg text-sm font-medium transition-colors whitespace-nowrap amazon-btn"
    >
      Amazonで見る
    </AffiliateLink>
  );
}

export default function RankingList({ products, ranked = true }: { products: Product[]; ranked?: boolean }) {
  if (products.length === 0) return null;

  return (
    <div className="my-6 space-y-4">
      {products.map((product, i) => (
        <div
          key={product.id}
          className="relative bg-white rounded-xl border border-line p-5"
        >
          {product.affiliateUrl && <RakutenDealStamp />}
          {ranked && <p className="mb-3 inline-flex rounded-full border border-lake-100 bg-lake-50 px-3 py-1 text-sm font-medium text-lake-700">{i + 1}位</p>}
          {/* Header row: rank + image + (name on desktop) */}
          <div className="flex gap-4 items-start">
            {product.imageUrl && (
              <div className="flex-shrink-0 w-16 h-16 sm:w-24 sm:h-24 rounded-lg overflow-hidden bg-mist relative">
                <Image
                  src={sizedImageUrl(product.imageUrl, 192)}
                  alt={product.name}
                  fill
                  sizes="96px"
                  className="object-contain p-2"
                  loading="lazy"
                />
              </div>
            )}

            <div className="flex-1 min-w-0">
              {product.brand && (
                <p className="text-xs text-slate-500 tracking-wide">{product.brand}</p>
              )}
              <h3 className="font-semibold text-ink-strong mb-1 leading-relaxed">{product.name}</h3>
              {product.price > 0 && (
                <span className="text-lg font-semibold text-lake-700 tracking-tight block mt-1">
                  ¥{product.price.toLocaleString()}
                </span>
              )}
            </div>
          </div>

          {/* Description */}
          {product.description && (
            <p className="text-base text-slate-600 leading-relaxed mt-3">
              {product.description}
            </p>
          )}

          {/* CTA row */}
          <div className="mt-4 flex flex-col sm:flex-row sm:flex-wrap gap-2">
            {isAmazonPrimary(product) && <AmazonButton product={product} />}
            {product.affiliateUrl && (
              <AffiliateLink
                href={product.affiliateUrl}
                productId={product.id}
                placement="ranking"
                productName={product.name}
                price={product.price}
                rank={isAmazonPrimary(product) ? 2 : 1}
                store="rakuten"
                className="inline-flex items-center justify-center min-h-11 px-4 py-3 rounded-lg text-sm font-medium text-white transition-colors whitespace-nowrap rakuten-btn"
              >
                楽天市場で見る
              </AffiliateLink>
            )}
            {!isAmazonPrimary(product) && <AmazonButton product={product} />}
            {product.yahooUrl && (
              <AffiliateLink
                href={product.yahooUrl}
                productId={product.id}
                placement="ranking"
                productName={product.name}
                price={product.price}
                rank={3}
                store="yahoo"
                className="inline-flex items-center justify-center min-h-11 px-4 py-3 rounded-lg text-sm font-medium border border-red-200 text-red-600 hover:bg-red-50 transition-colors whitespace-nowrap"
              >
                Yahoo!で見る
              </AffiliateLink>
            )}
            {product.affiliateUrl && (
              <AffiliateLink
                href={product.affiliateUrl}
                productId={product.id}
                placement="reviews_link"
                productName={product.name}
                price={product.price}
                store="rakuten"
                className="inline-flex min-h-11 items-center justify-center text-sm text-slate-500 hover:text-lake-600 underline underline-offset-2 transition-colors whitespace-nowrap sm:ml-1"
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
