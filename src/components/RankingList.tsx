import { Product } from "@/lib/types";

const medalColors = ["bg-yellow-400", "bg-gray-300", "bg-amber-600"];
const medalLabels = ["1位", "2位", "3位"];

export default function RankingList({ products }: { products: Product[] }) {
  if (products.length === 0) return null;

  return (
    <div className="my-6 space-y-4">
      {products.map((product, i) => (
        <div
          key={product.id}
          className="flex gap-4 bg-white rounded-xl shadow-sm border p-5 hover:shadow-md transition"
        >
          {/* Rank badge */}
          <div className="flex-shrink-0">
            <div
              className={`w-10 h-10 rounded-full flex items-center justify-center text-white font-bold text-sm ${
                i < 3 ? medalColors[i] : "bg-gray-400"
              }`}
            >
              {i < 3 ? medalLabels[i] : `${i + 1}位`}
            </div>
          </div>

          {/* Image */}
          {product.imageUrl && (
            <div className="flex-shrink-0 w-24 h-24 rounded-lg overflow-hidden bg-gray-100">
              <img
                src={product.imageUrl}
                alt={product.name}
                className="w-full h-full object-cover"
              />
            </div>
          )}

          {/* Content */}
          <div className="flex-1 min-w-0">
            {product.brand && (
              <p className="text-xs text-gray-400">{product.brand}</p>
            )}
            <h3 className="font-bold text-gray-800 mb-1">{product.name}</h3>
            {product.rating > 0 && (
              <div className="text-yellow-400 text-sm mb-1">
                {"★".repeat(Math.floor(product.rating))}
                {product.rating % 1 >= 0.5 ? "☆" : ""}
                <span className="text-gray-500 ml-1">{product.rating}</span>
              </div>
            )}
            {product.description && (
              <p className="text-sm text-gray-600 line-clamp-2">
                {product.description}
              </p>
            )}
          </div>

          {/* Price + CTA */}
          <div className="flex-shrink-0 flex flex-col items-end justify-between gap-2">
            {product.price > 0 && (
              <span className="text-lg font-bold text-red-600">
                ¥{product.price.toLocaleString()}
              </span>
            )}
            <div className="flex flex-col gap-1.5">
              {product.affiliateUrl && (
                <a
                  href={product.affiliateUrl}
                  target="_blank"
                  rel="noopener noreferrer nofollow sponsored"
                  className="bg-[#BF0000] hover:bg-red-700 text-white px-4 py-2 rounded-lg text-xs font-bold transition whitespace-nowrap text-center"
                >
                  楽天で見る →
                </a>
              )}
              {product.amazonUrl && (
                <a
                  href={product.amazonUrl}
                  target="_blank"
                  rel="noopener noreferrer nofollow sponsored"
                  className="bg-[#FF9900] hover:bg-amber-500 text-white px-4 py-2 rounded-lg text-xs font-bold transition whitespace-nowrap text-center block"
                >
                  Amazonで見る →
                </a>
              )}
            </div>
          </div>
        </div>
      ))}
    </div>
  );
}
