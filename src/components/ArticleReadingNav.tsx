import { BookOpen, List, Table2, ShoppingBag } from "lucide-react";
import ArticleNavigationLink from "./ArticleNavigationLink";
import type { ArticleDestination } from "@/lib/articleNavigation";

export default function ArticleReadingNav({ articleSlug, hasToc, hasComparison, hasProducts }: {
  articleSlug: string;
  hasToc: boolean;
  hasComparison: boolean;
  hasProducts: boolean;
}) {
  const links: { destination: ArticleDestination; href: string; label: string; icon: typeof List }[] = [
    hasToc
      ? { destination: "toc", href: "#article-toc", label: "目次", icon: List }
      : { destination: "body", href: "#article-reading-content", label: "本文", icon: BookOpen },
  ];
  if (hasComparison) links.push({ destination: "comparison", href: "#article-comparison", label: "比較表", icon: Table2 });
  if (hasProducts) links.push({ destination: "products", href: "#article-shopping", label: "商品価格", icon: ShoppingBag });
  if (links.length < 2) return null;

  return (
    <nav aria-label="記事内の移動" className="article-reading-nav sticky top-16 z-30 -mx-5 mb-6 grid grid-flow-col auto-cols-fr gap-1 border-y border-line bg-white/95 p-2 backdrop-blur-sm sm:static sm:mx-0 sm:rounded-xl sm:border">
      {links.map(({ destination, href, label, icon: Icon }) => (
        <ArticleNavigationLink key={destination} href={href} articleSlug={articleSlug} destination={destination} area="reading_nav" className="flex min-h-11 items-center justify-center gap-1.5 rounded-lg px-2 text-sm font-medium text-lake-700 hover:bg-lake-50 transition">
          <Icon size={16} aria-hidden="true" className="shrink-0" />{label}
        </ArticleNavigationLink>
      ))}
    </nav>
  );
}
