import { Product } from "@/lib/types";
import { isAmazonPrimary } from "@/lib/affiliate-priority";
import { getProductSpecs } from "@/lib/productSpecs";
import AffiliateLink from "./AffiliateLink";

function AmazonButton({ product }: { product: Product }) {
  if (!product.amazonUrl) return null;
  return (
    <AffiliateLink
      href={product.amazonUrl}
      productId={product.id}
      placement="comparison_table"
      productName={product.name}
      price={product.price}
      rank={isAmazonPrimary(product) ? 1 : 2}
      store="amazon"
      className="inline-flex items-center justify-center px-4 py-2 rounded-lg text-xs font-medium transition-colors amazon-btn"
    >
      Amazonで見る
    </AffiliateLink>
  );
}

export default function ComparisonTable({ products }: { products: Product[] }) {
  if (products.length === 0) return null;

  const specs = new Map(products.map((p) => [p.id, new Map(getProductSpecs(p))]));
  const allKeys = new Set(products.flatMap((p) => [...specs.get(p.id)!.keys()]));
  const specKeys = [...allKeys].filter((key) => {
    const filled = products.filter((p) => specs.get(p.id)?.has(key)).length;
    return filled > 0 && (products.length < 4 || filled * 2 >= products.length);
  });

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
                <div className="text-xs font-normal text-slate-400 mb-0.5 tracking-wide">
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
                  {p.price > 0 ? `¥${p.price.toLocaleString()}` : "販売店で確認"}
                </span>
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
                  {specs.get(p.id)?.get(key) || (
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
                  {isAmazonPrimary(p) && <AmazonButton product={p} />}
                  {p.affiliateUrl ? (
                    <AffiliateLink
                      href={p.affiliateUrl}
                      productId={p.id}
                      placement="comparison_table"
                      productName={p.name}
                      price={p.price}
                      rank={isAmazonPrimary(p) ? 2 : 1}
                      store="rakuten"
                      className="inline-flex items-center justify-center px-4 py-2 rounded-lg text-xs font-medium text-white transition-colors rakuten-btn"
                    >
                      楽天市場で見る
                    </AffiliateLink>
                  ) : (
                    // 購入リンクが無い商品。specsに「入手方法」があればその実情を
                    // 表示する（例: メーカー公式ストア限定の抽選販売品）。
                    // 一律「準備中」だと入手不可の商品で誤解を招くため
                    !isAmazonPrimary(p) && (
                      <span className="text-slate-400 text-xs">
                        {p.specs?.["入手方法"] ?? "準備中"}
                      </span>
                    )
                  )}
                  {!isAmazonPrimary(p) && <AmazonButton product={p} />}
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
                      placement="reviews_link"
                      productName={p.name}
                      store="rakuten"
                      className="text-center text-xs text-slate-500 hover:text-lake-600 underline underline-offset-2 transition-colors pt-1"
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
