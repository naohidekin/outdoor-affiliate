import Image from "next/image";
import { Product } from "@/lib/types";

interface Props {
  productA: Product;
  productB: Product;
}

export default function HeroSplit({ productA, productB }: Props) {
  const shortName = (name: string) => name.substring(0, 18);

  return (
    <div className="relative w-full h-[200px] md:h-[280px] overflow-hidden rounded-xl mb-8 flex">
      {/* 左パネル */}
      <div className="relative w-1/2 bg-white flex flex-col items-center justify-center p-4">
        <div className="relative w-full flex-1">
          <Image
            src={productA.imageUrl}
            alt={productA.name}
            fill
            sizes="(max-width: 896px) 50vw, 448px"
            className="object-contain"
            priority
          />
        </div>
        <p className="text-[11px] font-semibold text-ink-strong text-center mt-2 leading-tight line-clamp-2 w-full">
          {shortName(productA.name)}
        </p>
      </div>

      {/* VS バッジ */}
      <div className="absolute left-1/2 top-1/2 -translate-x-1/2 -translate-y-1/2 z-10
                      w-9 h-9 rounded-full bg-slate-700 text-white
                      flex items-center justify-center text-xs font-bold shadow-lg">
        VS
      </div>

      {/* 仕切り線 */}
      <div className="absolute left-1/2 top-0 bottom-0 w-px bg-line-soft" />

      {/* 右パネル */}
      <div className="relative w-1/2 bg-white flex flex-col items-center justify-center p-4">
        <div className="relative w-full flex-1">
          <Image
            src={productB.imageUrl}
            alt={productB.name}
            fill
            sizes="(max-width: 896px) 50vw, 448px"
            className="object-contain"
            priority
          />
        </div>
        <p className="text-[11px] font-semibold text-ink-strong text-center mt-2 leading-tight line-clamp-2 w-full">
          {shortName(productB.name)}
        </p>
      </div>
    </div>
  );
}
