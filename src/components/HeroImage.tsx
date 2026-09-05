import { Article, Product } from "@/lib/types";
import { getHeroType } from "@/lib/hero-type";
import HeroTile from "./HeroTile";
import HeroSplit from "./HeroSplit";
import HeroPhoto from "./HeroPhoto";
import { getPrimaryProducts } from "@/lib/articleEditorial";

interface Props {
  article: Article;
  products: Product[];
}

// 楽天マーケット出品者画像（バッジ・加工入り）はヒーローに不適
function isCleanImage(url: string): boolean {
  return !url.includes("thumbnail.image.rakuten.co.jp");
}

export default function HeroImage({ article, products }: Props) {
  const type = getHeroType(article.slug);
  const primaryProducts = getPrimaryProducts(article, products);
  const withImages = primaryProducts.filter((p) => p.imageUrl);
  const cleanImages = withImages.filter((p) => isCleanImage(p.imageUrl));

  if (type === "tile" && cleanImages.length >= 2) {
    return <HeroTile products={cleanImages} />;
  }

  if (type === "split" && cleanImages.length >= 2) {
    // 3商品以上の比較を、先頭2商品だけの対決として見せない。
    if (primaryProducts.length >= 3) {
      return <HeroTile products={cleanImages} />;
    }
    return <HeroSplit productA={cleanImages[0]} productB={cleanImages[1]} />;
  }

  // photo / フォールバック: eyecatch → クリーンな製品画像
  const src = article.eyecatch ?? cleanImages[0]?.imageUrl;
  if (src) {
    return <HeroPhoto src={src} alt={article.title} />;
  }

  return null;
}
