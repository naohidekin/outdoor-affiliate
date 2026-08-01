"use client";

import type { ReactNode } from "react";
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
}: {
  href?: string;
  children?: ReactNode;
}) {
  const isInternal =
    !href ||
    href.startsWith("/") ||
    href.startsWith("#") ||
    href.includes("camp-gear-lab.com");
  const store = !isInternal && href ? detectAffiliateStore(href) : null;

  if (isInternal) {
    return <a href={href}>{children}</a>;
  }
  return (
    <a
      href={href}
      target="_blank"
      rel={store ? "nofollow sponsored noopener noreferrer" : "noopener noreferrer"}
      {...(store &&
        href && {
          onClick: () =>
            trackAffiliateClick(href, "inline", store, {
              placement: "body_text",
            }),
        })}
    >
      {children}
    </a>
  );
}
