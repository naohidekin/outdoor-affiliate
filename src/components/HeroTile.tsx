import Image from "next/image";
import { Product } from "@/lib/types";
import { sizedImageUrl } from "@/lib/imageSize";
import { productImagePresentation } from "@/lib/productImagePresentation";

interface Props {
  products: Product[];
}

export default function HeroTile({ products }: Props) {
  const images = products.filter((p) => p.imageUrl).slice(0, 6);
  const cols = Math.min(images.length, 3);

  return (
    <div
      className={`grid w-full overflow-hidden rounded-xl mb-8 bg-mist ${cols === 1 ? "grid-cols-1" : cols === 2 ? "grid-cols-2" : "grid-cols-2 md:grid-cols-3"}`}
    >
      {images.map((p, i) => (
        <figure
          key={p.id}
          className="flex min-w-0 flex-col overflow-hidden bg-white border-r border-line-soft last:border-r-0"
        >
          <div className="relative mx-auto h-40 md:h-48 w-full max-w-48 overflow-hidden">
            <Image
              src={sizedImageUrl(p.imageUrl, 600)}
              alt={p.name}
              fill
              sizes="192px"
              className="object-contain p-3"
              style={productImagePresentation(p.imageUrl)}
              // preloadはLCP候補（先頭タイル）だけ。全タイルを先読みすると
              // かえって重要リソースを遅らせる
              preload={i === 0}
            />
          </div>
          <figcaption className="px-2 pb-3 text-center text-xs leading-relaxed text-slate-600 line-clamp-3">
            {p.name.replace(p.brand, "").trim()}
          </figcaption>
        </figure>
      ))}
    </div>
  );
}
