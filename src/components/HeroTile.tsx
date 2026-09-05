import Image from "next/image";
import { Product } from "@/lib/types";
import { sizedImageUrl } from "@/lib/imageSize";

interface Props {
  products: Product[];
}

export default function HeroTile({ products }: Props) {
  const images = products.filter((p) => p.imageUrl).slice(0, 6);
  const cols = images.length <= 3 ? images.length : 3;

  return (
    <div
      className="w-full h-[200px] md:h-[300px] overflow-hidden rounded-xl mb-8 bg-mist"
      style={{ display: "grid", gridTemplateColumns: `repeat(${cols}, 1fr)` }}
    >
      {images.map((p, i) => (
        <figure
          key={p.id}
          className="flex min-w-0 flex-col overflow-hidden bg-white border-r border-line-soft last:border-r-0"
        >
          <div className="relative min-h-0 flex-1">
            <Image
              src={sizedImageUrl(p.imageUrl, 600)}
              alt={p.name}
              fill
              sizes={`(max-width: 896px) ${Math.floor(100 / cols)}vw, ${Math.floor(896 / cols)}px`}
              className="object-contain p-3"
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
