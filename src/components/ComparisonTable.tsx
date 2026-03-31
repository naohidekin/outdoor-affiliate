import { Product } from "@/lib/types";

// 勝り負けを強調したいフィールド（値が低い方が良い場合はtrue）
const LOWER_IS_BETTER: Record<string, boolean> = {};

export default function ComparisonTable({ products }: { products: Product[] }) {
  if (products.length === 0) return null;

  const allKeys = new Set<string>();
  products.forEach((p) => Object.keys(p.specs).forEach((k) => allKeys.add(k)));
  const specKeys = Array.from(allKeys);

  return (
    <div className="overflow-x-auto my-8 rounded-2xl shadow-lg border border-gray-100">
      <table className="w-full border-collapse bg-white">
        {/* ヘッダー */}
        <thead>
          <tr>
            <th className="bg-gray-800 text-white px-5 py-4 text-left text-sm font-bold w-1/3 rounded-tl-2xl">
              比較項目
            </th>
            {products.map((p, i) => (
              <th
                key={p.id}
                className={`px-5 py-4 text-center text-sm font-bold ${
                  i === 0
                    ? "bg-green-700 text-white"
                    : "bg-green-500 text-white"
                } ${i === products.length - 1 ? "rounded-tr-2xl" : ""}`}
              >
                <div className="text-xs font-normal opacity-80 mb-0.5">{p.brand}</div>
                <div className="leading-tight">{p.name.replace(p.brand + " ", "")}</div>
              </th>
            ))}
          </tr>
        </thead>

        <tbody>
          {/* 価格行 */}
          <tr className="border-b border-gray-100 bg-red-50">
            <td className="px-5 py-4 text-sm font-bold text-gray-700 flex items-center gap-2">
              <span className="inline-block w-2 h-2 rounded-full bg-red-400"></span>
              価格
            </td>
            {products.map((p) => (
              <td key={p.id} className="px-5 py-4 text-center">
                <span className="text-xl font-black text-red-600">
                  ¥{p.price.toLocaleString()}
                </span>
                <span className="text-xs text-gray-400 ml-1">円</span>
              </td>
            ))}
          </tr>

          {/* 評価行 */}
          <tr className="border-b border-gray-100 bg-yellow-50">
            <td className="px-5 py-4 text-sm font-bold text-gray-700 flex items-center gap-2">
              <span className="inline-block w-2 h-2 rounded-full bg-yellow-400"></span>
              総合評価
            </td>
            {products.map((p) => (
              <td key={p.id} className="px-5 py-4 text-center">
                <div className="flex justify-center gap-0.5">
                  {[1, 2, 3, 4, 5].map((star) => (
                    <span
                      key={star}
                      className={`text-lg ${
                        star <= Math.floor(p.rating)
                          ? "text-yellow-400"
                          : star - 0.5 <= p.rating
                          ? "text-yellow-300"
                          : "text-gray-200"
                      }`}
                    >
                      ★
                    </span>
                  ))}
                </div>
                <div className="text-xs text-gray-500 mt-0.5">{p.rating} / 5</div>
              </td>
            ))}
          </tr>

          {/* スペック行 */}
          {specKeys.map((key, i) => (
            <tr
              key={key}
              className={`border-b border-gray-100 ${
                i % 2 === 0 ? "bg-white" : "bg-gray-50"
              }`}
            >
              <td className="px-5 py-3.5 text-sm font-semibold text-gray-600">
                {key}
              </td>
              {products.map((p) => (
                <td
                  key={p.id}
                  className="px-5 py-3.5 text-sm text-center text-gray-700"
                >
                  {p.specs[key] || (
                    <span className="text-gray-300">—</span>
                  )}
                </td>
              ))}
            </tr>
          ))}

          {/* 購入リンク行 */}
          <tr className="bg-gray-800 rounded-b-2xl">
            <td className="px-5 py-4 text-sm font-bold text-gray-300 rounded-bl-2xl">
              購入する
            </td>
            {products.map((p, i) => (
              <td
                key={p.id}
                className={`px-5 py-4 text-center ${
                  i === products.length - 1 ? "rounded-br-2xl" : ""
                }`}
              >
                <div className="flex flex-col gap-2 items-center">
                  {p.affiliateUrl ? (
                    <a
                      href={p.affiliateUrl}
                      target="_blank"
                      rel="noopener noreferrer nofollow sponsored"
                      className="inline-block bg-[#BF0000] hover:bg-red-700 text-white px-4 py-2 rounded-full text-xs font-bold transition shadow-md hover:shadow-lg w-full text-center"
                    >
                      楽天で見る →
                    </a>
                  ) : (
                    <span className="text-gray-500 text-xs">楽天：準備中</span>
                  )}
                  {p.amazonUrl ? (
                    <a
                      href={p.amazonUrl}
                      target="_blank"
                      rel="noopener noreferrer nofollow sponsored"
                      className="inline-block bg-[#FF9900] hover:bg-amber-500 text-white px-4 py-2 rounded-full text-xs font-bold transition shadow-md hover:shadow-lg w-full text-center"
                    >
                      Amazonで見る →
                    </a>
                  ) : (
                    <span className="text-gray-500 text-xs">Amazon：準備中</span>
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
