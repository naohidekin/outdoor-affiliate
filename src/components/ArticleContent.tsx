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
import { headingId } from "@/lib/toc";
import type { ReactNode } from "react";

// 見出しレンダラー用: 子要素（strong/リンク等を含みうる）を平文化する。
// 目次（lib/toc.ts extractToc）と同じ headingId に通すことでアンカー一致を保証
function textOf(node: ReactNode): string {
  if (typeof node === "string" || typeof node === "number") return String(node);
  if (Array.isArray(node)) return node.map(textOf).join("");
  if (node && typeof node === "object" && "props" in node)
    return textOf((node as { props: { children?: ReactNode } }).props.children);
  return "";
}

interface Props {
  content: string;
  products: Product[];
  showProductFallback?: boolean;
}

export default function ArticleContent({ content, products, showProductFallback = true }: Props) {
  const productMap = new Map(products.map((p) => [p.id, p]));

  // {{price:商品ID}} を現在の登録価格に差し替える。
  // 本文に金額を文字列で焼き込むと、商品データを直しても本文が古いまま残る
  // （2026-08-03に10記事で発覚。クーポン価格を「実売価格」と書いた記事もあった）。
  // 分割ではなく置換で処理するので、表のセル内や文中でも使える。
  // 価格未登録・IDの打ち間違いはタグを消して黙って本文を通す（記号の露出を防ぐ）
  const resolved = content.replace(
    /\{\{price:([^}]+)\}\}/g,
    (_all, rawId: string) => {
      const p = productMap.get(rawId.trim());
      return p?.price ? `${p.price.toLocaleString()}円` : "";
    }
  );

  // Split content by custom tags
  const parts = resolved.split(
    /(\{\{(?:product|comparison|ranking|youtube):[^}]+\}\})/g
  );

  // フォールバック: productIds がありながら本文に商品タグが無い記事には
  // 末尾に順位のない商品一覧を挿入する。本文を分割する呼び出し元では無効にする。
  const hasProductTag = /\{\{(?:product|comparison|ranking):/.test(content);
  const showFallbackRanking = showProductFallback && !hasProductTag && products.length > 0;

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
                // 目次からのアンカージャンプ用ID。scroll-mt で固定ヘッダー分の
                // 逃げを確保
                h2: ({ children }) => (
                  <h2 id={headingId(textOf(children))} className="scroll-mt-24">
                    {children}
                  </h2>
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
          <RankingList products={products} ranked={false} />
        </div>
      )}
    </div>
  );
}
