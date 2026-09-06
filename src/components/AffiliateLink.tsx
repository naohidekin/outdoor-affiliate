"use client";

import { useEffect, useRef } from "react";
import { usePathname } from "next/navigation";
import { observeOffer } from "@/lib/observeOffer";
import { trackEvent } from "@/lib/trackEvent";
import {
  trackAffiliateClick,
  priceBand,
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
  ariaLabel?: string;
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
  ariaLabel,
  children,
}: AffiliateLinkProps) {
  const linkRef = useRef<HTMLAnchorElement>(null);
  const pathname = usePathname();
  useEffect(() => {
    if (!linkRef.current) return;
    return observeOffer(linkRef.current, () => trackEvent("affiliate_offer_view", {
      product_id: productId, product_name: productName ?? "", merchant: store,
      placement: placement ?? "unknown", page_path: pathname,
      ...(price && price > 0 ? { price, price_band: priceBand(price) } : {}),
      ...(rank && rank > 0 ? { rank } : {}),
    }));
  }, [pathname, href, productId, productName, store, placement, price, rank]);

  function handleClick() {
    trackAffiliateClick(href, productId, store, { placement, productName, price, rank });
  }

  return (
    <a
      ref={linkRef}
      href={href}
      target="_blank"
      rel="noopener noreferrer nofollow sponsored"
      className={className}
      aria-label={ariaLabel}
      onClick={handleClick}
      onAuxClick={(event) => { if (event.button === 1) handleClick(); }}
    >
      {children}
    </a>
  );
}
