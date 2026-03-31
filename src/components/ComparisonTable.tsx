import { Product } from "@/lib/types";

export default function ComparisonTable({ products }: { products: Product[] }) {
  if (products.length === 0) return null;

  // Collect all spec keys
  const allKeys = new Set<string>();
  products.forEach((p) => Object.keys(p.specs).forEach((k) => allKeys.add(k)));
  const specKeys = Array.from(allKeys);

  return (
    <div className="overflow-x-auto my-6">
      <table className="w-full border-collapse bg-white rounded-xl shadow overflow-hidden">
        <thead>
          <tr className="bg-green-600 text-white">
            <th className="px-4 py-3 text-left text-sm font-semibold">項目</th>
            {products.map((p) => (
              <th key={p.id} className="px-4 py-3 text-center text-sm font-semibold">
                {p.name}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          <tr className="border-b">
            <td className="px-4 py-3 text-sm font-medium text-gray-700">ブランド</td>
            {products.map((p) => (
              <td key={p.id} className="px-4 py-3 text-sm text-center text-gray-600">
                {p.brand || "-"}
              </td>
            ))}
          </tr>
          <tr className="border-b bg-gray-50">
            <td className="px-4 py-3 text-sm font-medium text-gray-700">価格</td>
            {products.map((p) => (
              <td key={p.id} className="px-4 py-3 text-sm text-center font-bold text-red-600">
                {p.price > 0 ? `¥${p.price.toLocaleString()}` : "-"}
              </td>
            ))}
          </tr>
          <tr className="border-b">
            <td className="px-4 py-3 text-sm font-medium text-gray-700">評価</td>
            {products.map((p) => (
              <td key={p.id} className="px-4 py-3 text-sm text-center text-yellow-500">
                {"★".repeat(Math.floor(p.rating))}
                {p.rating % 1 >= 0.5 ? "☆" : ""}
                <span className="text-gray-500 ml-1">{p.rating}</span>
              </td>
            ))}
          </tr>
          {specKeys.map((key, i) => (
            <tr key={key} className={i % 2 === 0 ? "bg-gray-50" : ""}>
              <td className="px-4 py-3 text-sm font-medium text-gray-700">{key}</td>
              {products.map((p) => (
                <td key={p.id} className="px-4 py-3 text-sm text-center text-gray-600">
                  {p.specs[key] || "-"}
                </td>
              ))}
            </tr>
          ))}
          <tr className="bg-orange-50">
            <td className="px-4 py-3 text-sm font-medium text-gray-700">リンク</td>
            {products.map((p) => (
              <td key={p.id} className="px-4 py-3 text-center">
                {p.affiliateUrl ? (
                  <a
                    href={p.affiliateUrl}
                    target="_blank"
                    rel="noopener noreferrer nofollow"
                    className="inline-block bg-orange-500 hover:bg-orange-600 text-white px-4 py-2 rounded-lg text-xs font-semibold transition"
                  >
                    詳細を見る
                  </a>
                ) : (
                  "-"
                )}
              </td>
            ))}
          </tr>
        </tbody>
      </table>
    </div>
  );
}
