import Image from "next/image";
import { Product } from "@/lib/types";
import { isAmazonPrimary } from "@/lib/affiliate-priority";
import { sizedImageUrl } from "@/lib/imageSize";
import AffiliateLink from "./AffiliateLink";
import RakutenDealStamp from "./RakutenDealStamp";

export default function ProductCard({ product }: { product: Product }) {
  const amazonFirst = isAmazonPrimary(product);
  // どちらのモールを上に出したかを計測で追えるようにする。
  // 価格帯ごとの出し分け（affiliate-priority.ts）が効いているかの検証に要る
  const amazonBtn = product.amazonUrl ? (
    <AffiliateLink
      href={product.amazonUrl}
      productId={product.id}
      placement="product_card"
      productName={product.name}
      price={product.price}
      rank={amazonFirst ? 1 : 2}
      store="amazon"
      className="inline-flex items-center justify-center px-5 py-2 rounded-lg text-sm font-medium transition-colors amazon-btn"
    >
      Amazonで見る
    </AffiliateLink>
  ) : null;
  return (
    <div className="relative border border-line rounded-xl overflow-hidden bg-white">
      {product.affiliateUrl && <RakutenDealStamp />}
      {product.imageUrl && (
        <div className="relative h-64 sm:h-96 bg-white overflow-hidden">
          <Image
            src={sizedImageUrl(product.imageUrl, 800)}
            alt={product.name}
            fill
            sizes="(max-width: 768px) 100vw, 800px"
            className="object-contain p-1"
            loading="lazy"
          />
        </div>
      )}
      <div className="p-5">
        {product.brand && (
          <p className="text-xs text-slate-500 mb-1 tracking-wide">{product.brand}</p>
        )}
        <h3 className="font-semibold text-ink-strong mb-2 leading-snug">{product.name}</h3>
        {product.rating > 0 && (
          <div className="flex items-center gap-1 mb-2">
            <span className="text-amber-400 text-sm">
              {"★".repeat(Math.floor(product.rating))}
              {product.rating % 1 >= 0.5 ? "☆" : ""}
            </span>
            <span className="text-xs text-slate-500">{product.rating}</span>
          </div>
        )}
        {product.description && (
          <p className="text-sm text-slate-600 mb-3 line-clamp-3 leading-relaxed">
            {product.description}
          </p>
        )}
        {Object.keys(product.specs).length > 0 && (
          <div className="text-xs text-slate-500 mb-3 space-y-1 border-t border-line-soft pt-3">
            {Object.entries(product.specs)
              .slice(0, 3)
              .map(([key, val]) => (
                <div key={key} className="flex justify-between">
                  <span>{key}</span>
                  <span className="text-ink">{val}</span>
                </div>
              ))}
          </div>
        )}
        <div className="mt-4">
          {product.price > 0 && (
            <span className="text-lg font-semibold text-lake-700 block mb-3 tracking-tight">
              ¥{product.price.toLocaleString()}
            </span>
          )}
          <div className="flex flex-col gap-2">
            {/* どの販路にもリンクが無い商品（メーカー公式限定の抽選販売品など）は
                空のCTA欄になるため、specsの「入手方法」を代わりに示す */}
            {!product.affiliateUrl &&
              !product.amazonUrl &&
              !product.yahooUrl &&
              product.specs?.["入手方法"] && (
                <p className="text-xs text-slate-500 bg-mist rounded-lg px-4 py-2.5 text-center">
                  {product.specs["入手方法"]}
                </p>
              )}
            {amazonFirst && amazonBtn}
            {product.affiliateUrl && (
              <AffiliateLink
                href={product.affiliateUrl}
                productId={product.id}
                placement="product_card"
                productName={product.name}
                price={product.price}
                rank={amazonFirst ? 2 : 1}
                store="rakuten"
                className="inline-flex items-center justify-center px-5 py-2 rounded-lg text-sm font-medium text-white transition-colors rakuten-btn"
              >
                楽天市場で見る
              </AffiliateLink>
            )}
            {!amazonFirst && amazonBtn}
            {product.yahooUrl && (
              <AffiliateLink
                href={product.yahooUrl}
                productId={product.id}
                placement="product_card"
                productName={product.name}
                price={product.price}
                rank={3}
                store="yahoo"
                className="inline-flex items-center justify-center px-5 py-2 rounded-lg text-sm font-medium border border-red-200 text-red-600 hover:bg-red-50 transition-colors"
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
                store="rakuten"
                className="text-center text-xs text-slate-500 hover:text-lake-600 underline underline-offset-2 transition-colors pt-1"
              >
                楽天で口コミをもっと見る →
              </AffiliateLink>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
