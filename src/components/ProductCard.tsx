import Image from "next/image";
import { Product } from "@/lib/types";
import AffiliateLink from "./AffiliateLink";

export default function ProductCard({ product }: { product: Product }) {
  return (
    <div className="border border-line rounded-xl overflow-hidden bg-white">
      {product.imageUrl && (
        <div className="aspect-video bg-mist overflow-hidden relative">
          <Image
            src={product.imageUrl}
            alt={product.name}
            fill
            sizes="(max-width: 768px) 100vw, 600px"
            className="object-cover"
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
            {product.affiliateUrl && (
              <AffiliateLink
                href={product.affiliateUrl}
                productId={product.id}
                store="rakuten"
                className="block bg-white hover:bg-lake-50 text-lake-700 border border-lake-600 px-5 py-2 rounded-lg text-sm font-medium transition text-center"
              >
                楽天で見る →
              </AffiliateLink>
            )}
            {product.amazonUrl && (
              <AffiliateLink
                href={product.amazonUrl}
                productId={product.id}
                store="amazon"
                className="block bg-white hover:bg-mist text-slate-700 border border-line px-5 py-2 rounded-lg text-sm font-medium transition text-center"
              >
                Amazonで見る →
              </AffiliateLink>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
