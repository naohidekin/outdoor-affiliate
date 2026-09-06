"use client";

import Link from "next/link";
import { trackEvent } from "@/lib/trackEvent";

export default function GuideLink({ href, guideId, placement, className, children }: {
  href: string; guideId: string; placement: "home" | "guide" | "article";
  className?: string; children: React.ReactNode;
}) {
  return <Link href={href} className={className} onClick={() => trackEvent("guide_navigation", {
    guide_id: guideId, placement, destination: href, page_path: window.location.pathname,
  })}>{children}</Link>;
}
