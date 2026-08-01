// Server Component。従来はファイル全体が "use client" で、react-markdown・
// remark-gfm・商品カード・比較表が全記事でクライアントバンドルに入っていた。
// クリック計測が必要な本文リンクだけ BodyLink（Client）に切り出している
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { Product } from "@/lib/types";
import ProductCard from "./ProductCard";
import ComparisonTable from "./ComparisonTable";
import RankingList from "./RankingList";
import YouTubeEmbed from "./YouTubeEmbed";
import BodyLink from "./BodyLink";

interface Props {
  content: string;
  products: Product[];
}

export default function ArticleContent({ content, products }: Props) {
  const productMap = new Map(products.map((p) => [p.id, p]));

  // Split content by custom tags
  const parts = content.split(
    /(\{\{(?:product|comparison|ranking|youtube):[^}]+\}\})/g
  );

  // フォールバック: productIds がありながら本文に商品タグが無い記事には
  // 末尾に RankingList を自動挿入する (画像が一切出ない問題の対策)
  const hasProductTag = /\{\{(?:product|comparison|ranking):/.test(content);
  const showFallbackRanking = !hasProductTag && products.length > 0;

  return (
    <div className="prose max-w-none">
      {parts.map((part, i) => {
        // Product card
        const productMatch = part.match(/\{\{product:([^}]+)\}\}/);
        if (productMatch) {
          const product = productMap.get(productMatch[1]);
          if (product) {
            return (
              <div key={i} className="not-prose my-6">
                <ProductCard product={product} />
              </div>
            );
          }
          return null;
        }

        // Comparison table
        const compMatch = part.match(/\{\{comparison:([^}]+)\}\}/);
        if (compMatch) {
          const ids = compMatch[1].split(",").map((s) => s.trim());
          const prods = ids
            .map((id) => productMap.get(id))
            .filter(Boolean) as Product[];
          if (prods.length > 0) {
            return (
              <div key={i} className="not-prose">
                <ComparisonTable products={prods} />
              </div>
            );
          }
          return null;
        }

        // Ranking
        const rankMatch = part.match(/\{\{ranking:([^}]+)\}\}/);
        if (rankMatch) {
          const ids = rankMatch[1].split(",").map((s) => s.trim());
          const prods = ids
            .map((id) => productMap.get(id))
            .filter(Boolean) as Product[];
          if (prods.length > 0) {
            return (
              <div key={i} className="not-prose">
                <RankingList products={prods} />
              </div>
            );
          }
          return null;
        }

        // YouTube埋め込み: {{youtube:動画ID}} / {{youtube:動画ID|キャプション}}
        // 第3フィールドは動画の公開日（VideoObject構造化データ用・表示には使わない）
        const ytMatch = part.match(/\{\{youtube:([A-Za-z0-9_-]{6,20})(?:\|([^}]*))?\}\}/);
        if (ytMatch) {
          const caption = ytMatch[2]?.split("|")[0]?.trim();
          return (
            <div key={i} className="not-prose">
              <YouTubeEmbed videoId={ytMatch[1]} caption={caption} />
            </div>
          );
        }

        // Regular markdown
        if (part.trim()) {
          return (
            <ReactMarkdown
              key={i}
              remarkPlugins={[remarkGfm]}
              components={{
                a: ({ href, children }) => (
                  <BodyLink href={href}>{children}</BodyLink>
                ),
                table: ({ children, ...props }) => (
                  <div style={{ overflowX: "auto", WebkitOverflowScrolling: "touch" }}>
                    <table {...props}>{children}</table>
                  </div>
                ),
              }}
            >
              {part}
            </ReactMarkdown>
          );
        }

        return null;
      })}

      {showFallbackRanking && (
        <div className="not-prose mt-12">
          <h2 className="text-2xl font-semibold text-ink-strong tracking-tight mb-6 pb-2 border-b border-lake-100">
            この記事で紹介した製品
          </h2>
          <RankingList products={products} />
        </div>
      )}
    </div>
  );
}
