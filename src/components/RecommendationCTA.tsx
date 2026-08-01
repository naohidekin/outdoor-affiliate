import Image from "next/image";
import { Product } from "@/lib/types";
import { isAmazonPrimary } from "@/lib/affiliate-priority";
import type { AffiliatePlacement } from "@/lib/trackAffiliateClick";
import AffiliateLink from "./AffiliateLink";

function AmazonButton({
  product,
  placement,
}: {
  product: Product;
  placement: AffiliatePlacement;
}) {
  if (!product.amazonUrl) return null;
  return (
    <AffiliateLink
      href={product.amazonUrl}
      productId={product.id}
      placement={placement}
      productName={product.name}
      store="amazon"
      className="flex-1 sm:flex-none text-center px-3 py-2 rounded-lg text-xs font-medium transition amazon-btn"
    >
      Amazonで見る
    </AffiliateLink>
  );
}

export default function RecommendationCTA({
  products,
  title,
  subtitle,
  placement = "recommended",
}: {
  products: Product[];
  title?: string;
  subtitle?: string;
  placement?: AffiliatePlacement;
}) {
  if (products.length === 0) return null;

  return (
    <div className="my-6 rounded-xl border border-lake-100 bg-lake-50/60 overflow-hidden">
      <div className="px-5 py-3 bg-lake-600 text-white">
        <p className="text-sm font-semibold">
          {title ?? `迷ったらこの${products.length}つ — まず候補を絞る`}
        </p>
        <p className="text-xs text-lake-100 mt-0.5">
          {subtitle ?? "予算・用途に合わせて選んでください"}
        </p>
      </div>
      <div className="divide-y divide-lake-100">
        {products.map((p, i) => {
          // 主要スペックを最大2件抽出
          const topSpecs = Object.entries(p.specs).slice(0, 2);
          return (
            <div key={p.id} className="flex flex-col sm:flex-row sm:items-center gap-3 px-5 py-4">
              <div className="flex items-start gap-3 flex-1 min-w-0">
                <span className="shrink-0 w-6 h-6 rounded-full bg-lake-600 text-white text-xs font-bold flex items-center justify-center">
                  {i + 1}
                </span>
                {p.imageUrl && (
                  <Image
                    src={p.imageUrl}
                    alt={p.name}
                    width={48}
                    height={48}
                    className="w-12 h-12 object-contain rounded shrink-0"
                  />
                )}
                <div className="min-w-0">
                  <p className="text-sm font-semibold text-ink-strong leading-snug">{p.name}</p>
                  <p className="text-base font-bold text-lake-700 mt-0.5">¥{p.price.toLocaleString()}</p>
                  {topSpecs.length > 0 && (
                    <p className="text-xs text-slate-500 mt-0.5">
                      {topSpecs.map(([k, v]) => `${k}: ${v}`).join(" / ")}
                    </p>
                  )}
                </div>
              </div>
              <div className="flex gap-2 shrink-0 sm:flex-col sm:w-32">
                {isAmazonPrimary(p) && <AmazonButton product={p} placement={placement} />}
                {p.affiliateUrl && (
                  <AffiliateLink
                    href={p.affiliateUrl}
                    productId={p.id}
                    placement={placement}
                    productName={p.name}
                    store="rakuten"
                    className="flex-1 sm:flex-none text-center text-white px-3 py-2 rounded-lg text-xs font-medium transition rakuten-btn"
                  >
                    楽天で見る
                  </AffiliateLink>
                )}
                {!isAmazonPrimary(p) && <AmazonButton product={p} placement={placement} />}
                {p.yahooUrl && (
                  <AffiliateLink
                    href={p.yahooUrl}
                    productId={p.id}
                    placement={placement}
                    productName={p.name}
                    store="yahoo"
                    className="flex-1 sm:flex-none text-center bg-white hover:bg-red-50 text-red-600 border border-red-200 px-3 py-2 rounded-lg text-xs font-medium transition"
                  >
                    Yahoo!で見る
                  </AffiliateLink>
                )}
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}
