import { Article, Product } from "@/lib/types";
import { getHeroType } from "@/lib/hero-type";
import HeroTile from "./HeroTile";
import HeroSplit from "./HeroSplit";
import HeroPhoto from "./HeroPhoto";

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
  const withImages = products.filter((p) => p.imageUrl);
  const cleanImages = withImages.filter((p) => isCleanImage(p.imageUrl));

  if (type === "tile" && cleanImages.length >= 2) {
    return <HeroTile products={cleanImages} />;
  }

  if (type === "split" && cleanImages.length >= 2) {
    // 1対多の比較記事（4商品以上）は1対1構図だと誤解を招くのでタイル型に切替
    if (cleanImages.length >= 4) {
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
