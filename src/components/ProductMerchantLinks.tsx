import type { Product } from "@/lib/types";
import type { AffiliatePlacement } from "@/lib/trackAffiliateClick";
import { getProductMerchants } from "@/lib/productMerchants";
import AffiliateLink from "./AffiliateLink";

export default function ProductMerchantLinks({ product, placement, layout = "responsive" }: {
  product: Product; placement: AffiliatePlacement; layout?: "responsive" | "stacked" | "sidebar";
}) {
  const merchants = getProductMerchants(product);
  const columns = layout === "stacked" ? "grid-cols-1" : layout === "sidebar"
    ? "grid-cols-1 min-[360px]:grid-cols-2 sm:grid-cols-1" : "grid-cols-1 min-[360px]:grid-cols-2";
  if (!merchants.length) return <p className="text-sm leading-relaxed text-slate-500">{product.specs?.["入手方法"] || "販売店リンクは現在掲載していません。"}</p>;
  return <div className="not-prose min-w-0">
    <p className="text-sm text-slate-600 mb-2">販売店で価格・在庫を確認</p>
    <div className={`grid gap-2 ${columns}`}>
      {merchants.map(({ href, store, label, rank }) => <AffiliateLink key={store} href={href} store={store} rank={rank}
        productId={product.id} productName={product.name} price={product.price} placement={placement}
        ariaLabel={`${product.name}の価格・在庫を${label}で確認（新しいタブ）`}
        className={`flex min-h-12 min-w-0 items-center justify-center gap-2 rounded-lg px-3 py-3 text-sm font-semibold leading-relaxed transition-colors ${store === "amazon" ? "amazon-btn" : store === "rakuten" ? "rakuten-btn text-white" : "border border-line bg-white text-ink hover:bg-mist"}`}>
        <span>{label}</span><span aria-hidden="true">↗</span>
      </AffiliateLink>)}
    </div>
    <p className="mt-2 text-xs leading-relaxed text-slate-500">送料・付属品・販売条件は各販売店でご確認ください。</p>
  </div>;
}
