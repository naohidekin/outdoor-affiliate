"use client";

import { useEffect } from "react";
import { usePathname } from "next/navigation";
import { capturePostHog, getPostHog, isAnalyticsPath, stopPostHogReplay } from "@/lib/posthogAnalytics";

export default function PostHogAnalytics() {
  const pathname = usePathname();
  useEffect(() => {
    if (!isAnalyticsPath(pathname)) { stopPostHogReplay(); return; }
    let cancelled = false;
    capturePostHog("$pageview", { page_path: pathname });
    const article = /^\/articles\/([^/]+)\/?$/.exec(pathname);
    if (article) {
      capturePostHog("article_view", { article_slug: article[1] });
      if (process.env.NEXT_PUBLIC_POSTHOG_REPLAY === "true") {
        void getPostHog().then((ph) => {
          if (!cancelled && window.location.pathname === pathname) ph?.startSessionRecording();
        }).catch(() => {});
      }
    }
    // Observe table headers: a very tall/wide table can never be 50% visible on mobile.
    let seen = false;
    const observer = typeof IntersectionObserver === "undefined" ? undefined : new IntersectionObserver((entries) => {
      if (!seen && document.visibilityState === "visible" && entries.some(e => e.isIntersecting)) {
        seen = true;
        capturePostHog("comparison_view", { page_path: pathname, ...(article ? { article_slug: article[1] } : {}) });
        observer?.disconnect();
        mutation.disconnect();
      }
    });
    const observeTables = () => document.querySelectorAll("table.product-comparison thead, [data-comparison-start]").forEach(el => observer?.observe(el));
    observeTables();
    // Supports streamed/late rendered article content.
    const mutation = new MutationObserver(observeTables);
    mutation.observe(document.body, { childList: true, subtree: true });
    return () => {
      cancelled = true;
      observer?.disconnect();
      mutation.disconnect();
      stopPostHogReplay();
    };
  }, [pathname]);
  return null;
}
