import Image from "next/image";
import { Product } from "@/lib/types";
import { isAmazonPrimary } from "@/lib/affiliate-priority";
import type { AffiliatePlacement } from "@/lib/trackAffiliateClick";
import AffiliateLink from "./AffiliateLink";
import { sizedImageUrl } from "@/lib/imageSize";
import { getProductSpecs } from "@/lib/productSpecs";
import type { EditorialPick } from "@/lib/articleEditorial";

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
      price={product.price}
      rank={isAmazonPrimary(product) ? 1 : 2}
      store="amazon"
      className="flex-1 sm:flex-none text-center min-h-11 px-3 py-3 rounded-lg text-sm font-medium transition amazon-btn"
    >
      Amazonで見る
    </AffiliateLink>
  );
}

export default function RecommendationCTA({
  products,
  title,
  subtitle,
  picks = [],
  placement = "recommended",
}: {
  products: Product[];
  title?: string;
  subtitle?: string;
  picks?: EditorialPick[];
  placement?: AffiliatePlacement;
}) {
  if (products.length === 0) return null;

  return (
    <div className="my-6 rounded-xl border border-lake-100 bg-lake-50/60 overflow-hidden">
      <div className="px-5 py-3 bg-lake-600 text-white">
        <p className="text-sm font-semibold">
          {title ?? (picks.length ? "条件に合うモデルを選ぶ" : "掲載モデルの価格を確認")}
        </p>
        <p className="text-xs text-lake-100 mt-0.5">
          {subtitle ?? "価格は登録時点の参考情報です。最新の価格・付属品は販売店で確認してください。"}
        </p>
      </div>
      <div className="divide-y divide-lake-100">
        {products.map((p) => {
          const topSpecs = getProductSpecs(p, 2);
          const pick = picks.find((entry) => entry.productId === p.id);
          return (
            <div key={p.id} className="flex flex-col sm:flex-row sm:items-center gap-3 px-5 py-4">
              <div className="flex-1 min-w-0">
                <div className="flex items-start gap-3">
                  {p.imageUrl && (
                    <Image
                      src={sizedImageUrl(p.imageUrl, 96)}
                      alt={p.name}
                      width={64}
                      height={64}
                      className="w-16 h-16 object-contain rounded-lg bg-white p-1 shrink-0"
                    />
                  )}
                  <div className="min-w-0">
                    {pick && (
                      <p className="text-sm font-semibold text-lake-700 mb-1">{pick.audience}</p>
                    )}
                    <p className="text-base font-semibold text-ink-strong leading-relaxed">{p.name}</p>
                    <p className="text-base font-bold text-lake-700 mt-1">{p.price > 0 ? `¥${p.price.toLocaleString()}` : "価格は販売店で確認"}</p>
                    {topSpecs.length > 0 && (
                      <p className="text-sm leading-relaxed text-slate-500 mt-0.5">
                        {topSpecs.map(([k, v]) => `${k}: ${v}`).join(" / ")}
                      </p>
                    )}
                  </div>
                </div>
                {pick && (
                  <div className="mt-3 space-y-1 text-sm leading-relaxed text-slate-600">
                    <p><span className="mr-2 rounded bg-white px-2 py-0.5 text-xs text-lake-700">{pick.evidence}</span>{pick.reason}</p>
                    <p><span className="font-medium text-ink">選ぶ前に：</span>{pick.caution}</p>
                  </div>
                )}
              </div>
              <div className="grid grid-cols-1 min-[360px]:grid-cols-2 gap-2 shrink-0 sm:flex sm:flex-col sm:w-40">
                {isAmazonPrimary(p) && <AmazonButton product={p} placement={placement} />}
                {p.affiliateUrl && (
                  <AffiliateLink
                    href={p.affiliateUrl}
                    productId={p.id}
                    placement={placement}
                    productName={p.name}
                    price={p.price}
                    rank={isAmazonPrimary(p) ? 2 : 1}
                    store="rakuten"
                    className="flex-1 sm:flex-none text-center text-white min-h-11 px-3 py-3 rounded-lg text-sm font-medium transition rakuten-btn"
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
                    className="flex-1 sm:flex-none text-center bg-white hover:bg-red-50 text-red-600 border border-red-200 min-h-11 px-3 py-3 rounded-lg text-sm font-medium transition"
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
