"use client";

interface AffiliateLinkProps {
  href: string;
  productId: string;
  store: "amazon" | "rakuten";
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
    // GA4カスタムイベントで計測
    if (typeof window !== "undefined" && "gtag" in window) {
      (window as unknown as { gtag: (...args: unknown[]) => void }).gtag("event", "affiliate_click", {
        product_id: productId,
        store,
        page_path: window.location.pathname,
      });
    }

    // ビーコンAPIでサーバーサイド記録（GA4が入っていない場合のフォールバック）
    try {
      const data = JSON.stringify({
        productId,
        store,
        path: window.location.pathname,
        timestamp: new Date().toISOString(),
      });
      navigator.sendBeacon("/api/track-click", data);
    } catch {
      // ignore
    }
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
