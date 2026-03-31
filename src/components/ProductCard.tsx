import { Product } from "@/lib/types";

export default function ProductCard({ product }: { product: Product }) {
  return (
    <div className="border rounded-xl overflow-hidden bg-white shadow-sm hover:shadow-md transition">
      {product.imageUrl && (
        <div className="aspect-video bg-gray-100 overflow-hidden">
          <img
            src={product.imageUrl}
            alt={product.name}
            className="w-full h-full object-cover"
          />
        </div>
      )}
      <div className="p-5">
        {product.brand && (
          <p className="text-xs text-gray-400 mb-1">{product.brand}</p>
        )}
        <h3 className="font-bold text-gray-800 mb-2">{product.name}</h3>
        {product.rating > 0 && (
          <div className="flex items-center gap-1 mb-2">
            <span className="text-yellow-400">
              {"★".repeat(Math.floor(product.rating))}
              {product.rating % 1 >= 0.5 ? "☆" : ""}
            </span>
            <span className="text-sm text-gray-500">{product.rating}</span>
          </div>
        )}
        {product.description && (
          <p className="text-sm text-gray-600 mb-3 line-clamp-3">
            {product.description}
          </p>
        )}
        {Object.keys(product.specs).length > 0 && (
          <div className="text-xs text-gray-500 mb-3 space-y-1">
            {Object.entries(product.specs)
              .slice(0, 3)
              .map(([key, val]) => (
                <div key={key} className="flex justify-between">
                  <span>{key}</span>
                  <span className="text-gray-700">{val}</span>
                </div>
              ))}
          </div>
        )}
        <div className="flex items-center justify-between mt-4">
          {product.price > 0 && (
            <span className="text-lg font-bold text-red-600">
              ¥{product.price.toLocaleString()}
            </span>
          )}
          {product.affiliateUrl && (
            <a
              href={product.affiliateUrl}
              target="_blank"
              rel="noopener noreferrer nofollow"
              className="bg-orange-500 hover:bg-orange-600 text-white px-5 py-2 rounded-lg text-sm font-semibold transition"
            >
              詳細を見る
            </a>
          )}
        </div>
      </div>
    </div>
  );
}
