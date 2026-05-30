import Image from "next/image";
import { Product } from "@/lib/types";

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
      {images.map((p) => (
        <div
          key={p.id}
          className="relative overflow-hidden bg-white border-r border-line-soft last:border-r-0"
        >
          <Image
            src={p.imageUrl}
            alt={p.name}
            fill
            sizes={`(max-width: 896px) ${Math.floor(100 / cols)}vw, ${Math.floor(896 / cols)}px`}
            className="object-contain p-3"
            priority
          />
        </div>
      ))}
    </div>
  );
}
