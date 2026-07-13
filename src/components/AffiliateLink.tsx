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
  className?: string;
  children: React.ReactNode;
}

export default function AffiliateLink({
  href,
  productId,
  store,
  placement,
  productName,
  className,
  children,
}: AffiliateLinkProps) {
  function handleClick() {
    trackAffiliateClick(href, productId, store, { placement, productName });
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
