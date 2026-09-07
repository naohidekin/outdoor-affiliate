import { Product } from "@/lib/types";
import { getProductSpecs } from "@/lib/productSpecs";
import ProductMerchantLinks from "./ProductMerchantLinks";
import TableScroll from "./TableScroll";

export default function ComparisonTable({ products }: { products: Product[] }) {
  if (products.length === 0) return null;

  const specs = new Map(products.map((p) => [p.id, new Map(getProductSpecs(p))]));
  const allKeys = new Set(products.flatMap((p) => [...specs.get(p.id)!.keys()]));
  const specKeys = [...allKeys].filter((key) => {
    const filled = products.filter((p) => specs.get(p.id)?.has(key)).length;
    return filled > 0 && (products.length < 4 || filled * 2 >= products.length);
  });

  return (
    <>
      <section className="not-prose my-7 space-y-4 md:hidden" aria-label="商品スペック比較">
        <p data-comparison-start className="text-sm leading-relaxed text-slate-600">商品ごとに仕様と購入先を確認できます。参考価格と販売店の現在価格は異なる場合があります。</p>
        {products.map((p) => (
          <div key={p.id} className="min-w-0 overflow-hidden rounded-xl border border-line bg-white p-4">
            <p className="text-xs text-slate-500">{p.brand}</p>
            <h3 className="mt-1 break-words text-base font-semibold leading-relaxed text-ink-strong">{p.name}</h3>
            <p className="my-3 text-sm text-slate-600">参考価格 <span className="font-semibold text-lake-700">{p.price > 0 ? `¥${p.price.toLocaleString()}` : "販売店で確認"}</span></p>
            <dl className="mb-4 divide-y divide-line-soft text-sm">
              {specKeys.slice(0, 3).map((key) => <div key={key} className="grid grid-cols-[minmax(0,1fr)_minmax(0,2fr)] gap-3 py-2">
                <dt className="break-words text-slate-500">{key}</dt><dd className="min-w-0 break-words text-ink">{specs.get(p.id)?.get(key) || "記載なし"}</dd>
              </div>)}
            </dl>
            {specKeys.length > 3 && <details className="mb-4 rounded-lg bg-mist p-3">
              <summary className="cursor-pointer py-1 text-sm font-medium">その他の仕様を見る</summary>
              <dl className="mt-2 space-y-3 text-sm">{specKeys.slice(3).map((key) => <div key={key}><dt className="text-slate-500">{key}</dt><dd className="mt-1 break-words text-ink">{specs.get(p.id)?.get(key) || "記載なし"}</dd></div>)}</dl>
            </details>}
            <ProductMerchantLinks product={p} placement="comparison_table" />
          </div>
        ))}
      </section>
      <div className="hidden md:block">
    <TableScroll label="商品スペック比較表">
      <table className="product-comparison border-collapse bg-white" style={{ width: `calc(var(--comparison-label-width) + ${products.length} * var(--comparison-product-width))` }}>
        <caption className="sr-only">掲載商品の価格と仕様の比較</caption>
        <colgroup>
          <col style={{ width: "var(--comparison-label-width)" }} />
          {products.map((p) => <col key={p.id} style={{ width: "var(--comparison-product-width)" }} />)}
        </colgroup>
        {/* ヘッダー */}
        <thead>
          <tr>
            <th scope="col" className="bg-ink-strong text-white px-4 py-4 text-left text-sm font-semibold sticky left-0 z-10">
              比較項目
            </th>
            {products.map((p) => (
              <th
                key={p.id}
                scope="col"
                className="bg-ink text-white px-4 py-4 text-center text-sm font-semibold border-l border-white/10"
              >
                <div className="text-xs font-normal text-slate-300 mb-1 tracking-wide">
                  {p.brand}
                </div>
                <div className="leading-relaxed">
                  {p.name.replace(p.brand + " ", "")}
                </div>
              </th>
            ))}
          </tr>
        </thead>

        <tbody>
          {/* 価格行 */}
          <tr className="border-b border-line bg-lake-50">
            <th scope="row" className="px-4 py-4 text-left text-sm font-semibold text-ink-strong sticky left-0 bg-lake-50 z-[5]">
              参考価格
            </th>
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
              <th scope="row" className={`px-4 py-3.5 text-left text-sm font-medium text-slate-600 sticky left-0 z-[5] ${i % 2 === 0 ? "bg-white" : "bg-mist"}`}>
                {key}
              </th>
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
            <th scope="row" className="px-4 py-4 text-left text-sm font-semibold text-slate-600 sticky left-0 bg-white z-[5]">
              販売店
            </th>
            {products.map((p) => (
              <td
                key={p.id}
                className="px-4 py-4 text-center border-l border-line-soft"
              >
                <ProductMerchantLinks product={p} placement="comparison_table" layout="stacked" />
              </td>
            ))}
          </tr>
        </tbody>
      </table>
    </TableScroll>
      </div>
    </>
  );
}
