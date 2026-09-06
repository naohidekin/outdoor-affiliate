import Image from "next/image";
import { Product } from "@/lib/types";
import { sizedImageUrl } from "@/lib/imageSize";
import ProductMerchantLinks from "./ProductMerchantLinks";
import { getProductSpecs } from "@/lib/productSpecs";
import RakutenDealStamp from "./RakutenDealStamp";

export default function ProductCard({ product }: { product: Product }) {
  const specs = getProductSpecs(product, 3);
  return (
    <div className="product-card relative border border-line rounded-2xl overflow-hidden bg-white">
      {product.affiliateUrl && <RakutenDealStamp />}
      {product.imageUrl && (
        <div className="relative h-52 sm:h-72 bg-white overflow-hidden">
          <Image
            src={sizedImageUrl(product.imageUrl, 800)}
            alt={product.name}
            fill
            sizes="(max-width: 768px) 100vw, 800px"
            className="object-contain p-5"
            loading="lazy"
          />
        </div>
      )}
      <div className="p-5">
        {product.brand && (
          <p className="text-xs text-slate-500 mb-1 tracking-wide">{product.brand}</p>
        )}
        <h3 className="font-semibold text-ink-strong mb-2 leading-snug">{product.name}</h3>
        {product.description && (
          <p className="text-base text-slate-600 mb-4 leading-relaxed">
            {product.description}
          </p>
        )}
        {specs.length > 0 && (
          <div className="text-sm text-slate-600 mb-4 space-y-3 border-t border-line-soft pt-4">
            {specs
              .map(([key, val]) => (
                <div key={key} className="grid grid-cols-[minmax(0,1fr)_minmax(0,2fr)] gap-4">
                  <span>{key}</span>
                  <span className="text-ink text-right break-words">{val}</span>
                </div>
              ))}
          </div>
        )}
        <div className="mt-4">
          {product.price > 0 && (
            <span className="text-lg font-semibold text-lake-700 block mb-3 tracking-tight">
              <span className="text-sm font-normal text-slate-500 mr-2">参考価格</span>¥{product.price.toLocaleString()}
            </span>
          )}
          <ProductMerchantLinks product={product} placement="product_card" />
        </div>
      </div>
    </div>
  );
}
