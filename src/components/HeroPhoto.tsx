import Image from "next/image";

interface Props {
  src: string;
  alt: string;
}

export default function HeroPhoto({ src, alt }: Props) {
  return (
    <div className="relative w-full h-[200px] md:h-[300px] overflow-hidden rounded-xl mb-8 bg-white">
      <Image
        src={src}
        alt={alt}
        fill
        sizes="(max-width: 896px) 100vw, 896px"
        className="object-contain"
        priority
      />
    </div>
  );
}
