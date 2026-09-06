"use client";

import type { ReactNode } from "react";
import {
  trackArticleNavigation,
  type ArticleDestination,
  type ArticleNavigationArea,
} from "@/lib/articleNavigation";

export default function ArticleNavigationLink({
  href, articleSlug, destination, area, targetSlug, className, children,
}: {
  href: string;
  articleSlug: string;
  destination: ArticleDestination;
  area: ArticleNavigationArea;
  targetSlug?: string;
  className?: string;
  children: ReactNode;
}) {
  return (
    <a href={href} className={className} onClick={(event) => {
      trackArticleNavigation(articleSlug, destination, area, targetSlug);
      if (!href.startsWith("#") || event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
      const target = document.getElementById(href.slice(1));
      if (!target) return;
      const details = target.closest("details");
      if (details) details.open = true;
      const focusTarget = target instanceof HTMLDetailsElement
        ? target.querySelector("summary")
        : target.querySelector<HTMLElement>('[role="region"]') ?? target;
      focusTarget?.focus({ preventScroll: true });
    }}>
      {children}
    </a>
  );
}
