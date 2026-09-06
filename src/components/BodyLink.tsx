"use client";

import type { ReactNode } from "react";
import { affiliateProductKey, isInternalArticleLink, type AffiliateProduct } from "@/lib/affiliateProduct";
import {
  detectAffiliateStore,
  trackAffiliateClick,
} from "@/lib/trackAffiliateClick";

// 記事本文（Markdown）内のリンク。クリック計測が必要なためここだけClient。
// rel はリンクの性質で分ける:
// - アフィリエイト: nofollow sponsored（広告リンクであることを検索エンジンに明示）
// - 一般の外部リンク（メーカー公式・医学的根拠等の出典）: noopener noreferrer のみ。
//   出典リンクまで sponsored にするとリンクの性質を誤って伝えることになる
// - 内部リンク: 属性なし
export default function BodyLink({
  href,
  children,
  product,
}: {
  href?: string;
  children?: ReactNode;
  product?: AffiliateProduct;
}) {
  const isInternal = isInternalArticleLink(href);
  const store = !isInternal && href ? detectAffiliateStore(href) : null;

  if (isInternal) {
    return <a href={href}>{children}</a>;
  }
  return (
    <a
      href={href}
      target="_blank"
      data-product-id={store ? product?.id || affiliateProductKey(href || "") || "inline" : undefined}
      rel={store ? "nofollow sponsored noopener noreferrer" : "noopener noreferrer"}
      {...(store &&
        href && {
          onClick: (event: React.MouseEvent<HTMLAnchorElement>) =>
            trackAffiliateClick(href, product?.id || affiliateProductKey(href) || "inline", store, {
              placement: "body_text",
              productName: product?.name,
              linkText: event.currentTarget.textContent || "",
            }),
        })}
    >
      {children}
    </a>
  );
}
