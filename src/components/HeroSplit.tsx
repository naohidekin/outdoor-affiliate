import Image from "next/image";
import { Product } from "@/lib/types";

interface Props {
  productA: Product;
  productB: Product;
}

export default function HeroSplit({ productA, productB }: Props) {
  const shortName = (name: string) =>
    name.replace(/\s+\S+$/, "").substring(0, 20);

  return (
    <div className="relative w-full h-[200px] md:h-[300px] overflow-hidden rounded-xl mb-8 bg-mist">
      {/* 左パネル */}
      <div
        className="absolute inset-0 overflow-hidden bg-white"
        style={{ clipPath: "polygon(0 0, 60% 0, 40% 100%, 0 100%)" }}
      >
        <Image
          src={productA.imageUrl}
          alt={productA.name}
          fill
          sizes="60vw"
          className="object-contain p-4"
          priority
        />
        <div className="absolute bottom-3 left-3 bg-black/50 text-white text-xs font-semibold px-2 py-1 rounded backdrop-blur-sm max-w-[40%] truncate">
          {shortName(productA.name)}
        </div>
      </div>

      {/* 右パネル */}
      <div
        className="absolute inset-0 overflow-hidden bg-mist"
        style={{ clipPath: "polygon(60% 0, 100% 0, 100% 100%, 40% 100%)" }}
      >
        <Image
          src={productB.imageUrl}
          alt={productB.name}
          fill
          sizes="60vw"
          className="object-contain p-4"
          priority
        />
        <div className="absolute bottom-3 right-3 bg-black/50 text-white text-xs font-semibold px-2 py-1 rounded backdrop-blur-sm max-w-[40%] truncate text-right">
          {shortName(productB.name)}
        </div>
      </div>

      {/* 中央ライン装飾 */}
      <div
        className="absolute inset-0 pointer-events-none"
        style={{
          background:
            "linear-gradient(to bottom-right, transparent calc(50% - 1px), var(--color-line) calc(50% - 1px), var(--color-line) calc(50% + 1px), transparent calc(50% + 1px))",
        }}
      />
    </div>
  );
}
