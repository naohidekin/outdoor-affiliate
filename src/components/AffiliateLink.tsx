"use client";

import { trackAffiliateClick, AffiliateStore } from "@/lib/trackAffiliateClick";

interface AffiliateLinkProps {
  href: string;
  productId: string;
  store: AffiliateStore;
  className?: string;
  children: React.ReactNode;
}

export default function AffiliateLink({
  href,
  productId,
  store,
  className,
  children,
}: AffiliateLinkProps) {
  function handleClick() {
    trackAffiliateClick(href, productId, store);
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
