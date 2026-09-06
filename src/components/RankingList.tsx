import Image from "next/image";
import { Product } from "@/lib/types";
import { sizedImageUrl } from "@/lib/imageSize";
import ProductMerchantLinks from "./ProductMerchantLinks";
import RakutenDealStamp from "./RakutenDealStamp";

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
                  <span className="text-sm font-normal text-slate-500 mr-2">参考価格</span>¥{product.price.toLocaleString()}
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
          <div className="mt-4">
            <ProductMerchantLinks product={product} placement="ranking" />
          </div>
        </div>
      ))}
    </div>
  );
}
