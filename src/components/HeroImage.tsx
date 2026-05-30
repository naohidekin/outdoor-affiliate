import { Article, Product } from "@/lib/types";
import { getHeroType } from "@/lib/hero-type";
import HeroTile from "./HeroTile";
import HeroSplit from "./HeroSplit";
import HeroPhoto from "./HeroPhoto";

interface Props {
  article: Article;
  products: Product[];
}

export default function HeroImage({ article, products }: Props) {
  const type = getHeroType(article.slug);
  const withImages = products.filter((p) => p.imageUrl);

  if (type === "tile" && withImages.length >= 2) {
    return <HeroTile products={withImages} />;
  }

  if (type === "split" && withImages.length >= 2) {
    return <HeroSplit productA={withImages[0]} productB={withImages[1]} />;
  }

  // photo / フォールバック: eyecatch → 最初の製品画像
  const src = article.eyecatch ?? withImages[0]?.imageUrl;
  if (src) {
    return <HeroPhoto src={src} alt={article.title} />;
  }

  return null;
}
