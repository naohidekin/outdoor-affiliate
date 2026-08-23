"use client";

import {
  trackAffiliateClick,
  AffiliateStore,
  AffiliatePlacement,
} from "@/lib/trackAffiliateClick";

interface AffiliateLinkProps {
  href: string;
  productId: string;
  store: AffiliateStore;
  placement?: AffiliatePlacement;
  productName?: string;
  /** 表示していた価格（円）。価格帯別のEPCを出すため */
  price?: number;
  /** そのカード内でのボタンの表示順。1が上 */
  rank?: number;
  className?: string;
  children: React.ReactNode;
}

export default function AffiliateLink({
  href,
  productId,
  store,
  placement,
  productName,
  price,
  rank,
  className,
  children,
}: AffiliateLinkProps) {
  function handleClick() {
    trackAffiliateClick(href, productId, store, { placement, productName, price, rank });
  }

  return (
    <a
      href={href}
      target="_blank"
      rel="noopener noreferrer nofollow sponsored"
      className={className}
      onClick={handleClick}
    >
      {children}
    </a>
  );
}
