import { Product } from "@/lib/types";
import AffiliateLink from "./AffiliateLink";

export default function ComparisonTable({ products }: { products: Product[] }) {
  if (products.length === 0) return null;

  const allKeys = new Set<string>();
  products.forEach((p) => Object.keys(p.specs).forEach((k) => allKeys.add(k)));
  const specKeys = Array.from(allKeys);

  return (
    <div className="overflow-x-auto my-8 rounded-xl border border-line">
      <table className="border-collapse bg-white" style={{ minWidth: `${Math.max(600, products.length * 160 + 120)}px` }}>
        {/* ヘッダー */}
        <thead>
          <tr>
            <th className="bg-ink-strong text-white px-4 py-4 text-left text-sm font-semibold sticky left-0 z-10 w-[120px] min-w-[120px]">
              比較項目
            </th>
            {products.map((p) => (
              <th
                key={p.id}
                className="bg-ink text-white px-4 py-4 text-center text-sm font-semibold border-l border-white/10 min-w-[150px]"
              >
                <div className="text-[11px] font-normal text-slate-400 mb-0.5 tracking-wide">
                  {p.brand}
                </div>
                <div className="leading-tight">
                  {p.name.replace(p.brand + " ", "")}
                </div>
              </th>
            ))}
          </tr>
        </thead>

        <tbody>
          {/* 価格行 */}
          <tr className="border-b border-line bg-lake-50">
            <td className="px-4 py-4 text-sm font-semibold text-ink-strong sticky left-0 bg-lake-50 z-[5]">
              価格
            </td>
            {products.map((p) => (
              <td key={p.id} className="px-4 py-4 text-center border-l border-line-soft">
                <span className="text-xl font-semibold text-lake-700 tracking-tight">
                  ¥{p.price.toLocaleString()}
                </span>
              </td>
            ))}
          </tr>

          {/* 評価行 */}
          <tr className="border-b border-line bg-white">
            <td className="px-4 py-4 text-sm font-semibold text-ink-strong sticky left-0 bg-white z-[5]">
              総合評価
            </td>
            {products.map((p) => (
              <td key={p.id} className="px-4 py-4 text-center border-l border-line-soft">
                <div className="flex justify-center gap-0.5">
                  {[1, 2, 3, 4, 5].map((star) => (
                    <span
                      key={star}
                      className={`text-lg ${
                        star <= Math.floor(p.rating)
                          ? "text-amber-400"
                          : star - 0.5 <= p.rating
                          ? "text-amber-300"
                          : "text-slate-200"
                      }`}
                    >
                      ★
                    </span>
                  ))}
                </div>
                <div className="text-xs text-slate-500 mt-0.5">{p.rating} / 5</div>
              </td>
            ))}
          </tr>

          {/* スペック行 */}
          {specKeys.map((key, i) => (
            <tr
              key={key}
              className={`border-b border-line ${
                i % 2 === 0 ? "bg-white" : "bg-mist"
              }`}
            >
              <td className={`px-4 py-3.5 text-sm font-medium text-slate-600 sticky left-0 z-[5] ${i % 2 === 0 ? "bg-white" : "bg-mist"}`}>
                {key}
              </td>
              {products.map((p) => (
                <td
                  key={p.id}
                  className="px-4 py-3.5 text-sm text-center text-ink border-l border-line-soft"
                >
                  {p.specs[key] || (
                    <span className="text-slate-300">—</span>
                  )}
                </td>
              ))}
            </tr>
          ))}

          {/* 購入リンク行 */}
          <tr className="bg-white border-t border-line">
            <td className="px-4 py-4 text-sm font-semibold text-slate-600 sticky left-0 bg-white z-[5]">
              購入する
            </td>
            {products.map((p) => (
              <td
                key={p.id}
                className="px-4 py-4 text-center border-l border-line-soft"
              >
                <div className="flex flex-col gap-2 items-stretch">
                  {p.affiliateUrl ? (
                    <AffiliateLink
                      href={p.affiliateUrl}
                      productId={p.id}
                      placement="comparison_table"
                      productName={p.name}
                      store="rakuten"
                      className="inline-flex items-center justify-center px-4 py-2 rounded-lg text-xs font-medium text-white transition-colors rakuten-btn"
                    >
                      楽天市場で見る
                    </AffiliateLink>
                  ) : (
                    <span className="text-slate-400 text-xs">準備中</span>
                  )}
                  {p.amazonUrl && (
                    <AffiliateLink
                      href={p.amazonUrl}
                      productId={p.id}
                      placement="comparison_table"
                      productName={p.name}
                      store="amazon"
                      className="inline-flex items-center justify-center px-4 py-2 rounded-lg text-xs font-medium transition-colors amazon-btn"
                    >
                      Amazonで見る
                    </AffiliateLink>
                  )}
                  {p.yahooUrl && (
                    <AffiliateLink
                      href={p.yahooUrl}
                      productId={p.id}
                      placement="comparison_table"
                      productName={p.name}
                      store="yahoo"
                      className="inline-flex items-center justify-center px-4 py-2 rounded-lg text-xs font-medium border border-red-200 text-red-600 hover:bg-red-50 transition-colors"
                    >
                      Yahoo!で見る
                    </AffiliateLink>
                  )}
                  {p.affiliateUrl && (
                    <AffiliateLink
                      href={p.affiliateUrl}
                      productId={p.id}
                      placement="comparison_table"
                      productName={p.name}
                      store="rakuten"
                      className="text-center text-[11px] text-slate-500 hover:text-lake-600 underline underline-offset-2 transition-colors pt-1"
                    >
                      楽天で口コミを見る →
                    </AffiliateLink>
                  )}
                </div>
              </td>
            ))}
          </tr>
        </tbody>
      </table>
    </div>
  );
}
