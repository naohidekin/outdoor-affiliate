import Image from "next/image";
import { sizedImageUrl } from "@/lib/imageSize";

interface Props {
  src: string;
  alt: string;
}

export default function HeroPhoto({ src, alt }: Props) {
  return (
    <div className="relative w-full h-[200px] md:h-[300px] overflow-hidden rounded-xl mb-8 bg-white">
      <Image
        src={sizedImageUrl(src, 1200)}
        alt={alt}
        fill
        sizes="(max-width: 896px) 100vw, 896px"
        className="object-contain"
        preload
      />
    </div>
  );
}
