import type { PostHog } from "posthog-js";

const allowedEvents = new Set([
  "$pageview", "article_view", "comparison_view", "affiliate_offer_view",
  "affiliate_click", "guide_navigation", "article_navigation",
]);
const allowedProperties = new Set([
  "page_path", "article_slug", "product_id", "product_name", "merchant",
  "placement", "price", "price_band", "rank", "destination", "source",
]);

export function isAnalyticsPath(path: string): boolean {
  return path === "/" || /^\/(articles|category|gear-guides)(\/|$)/.test(path);
}

/** Explicit fields only: no link URLs, query strings, form values or arbitrary text. */
export function posthogProperties(values: Record<string, string | number>) {
  return Object.fromEntries(Object.entries(values).filter(([key]) => allowedProperties.has(key)));
}

let client: PostHog | undefined;
let loading: Promise<PostHog | undefined> | undefined;

function enabled() {
  return typeof window !== "undefined"
    && window.location?.hostname === "camp-gear-lab.com"
    && isAnalyticsPath(window.location.pathname)
    && Boolean(process.env.NEXT_PUBLIC_POSTHOG_KEY)
    && /^https:\/\/(us|eu)\.i\.posthog\.com$/.test(process.env.NEXT_PUBLIC_POSTHOG_HOST || "");
}

export function getPostHog(): Promise<PostHog | undefined> {
  if (!enabled()) return Promise.resolve(undefined);
  if (client) return Promise.resolve(client);
  if (!loading) loading = import("posthog-js").then(({ default: posthog }) => {
    // Navigation may have changed during the dynamic import.
    if (!enabled()) { loading = undefined; return undefined; }
    posthog.init(process.env.NEXT_PUBLIC_POSTHOG_KEY!, {
      api_host: process.env.NEXT_PUBLIC_POSTHOG_HOST!,
      person_profiles: "never",
      autocapture: false,
      capture_pageview: false,
      capture_pageleave: false,
      capture_dead_clicks: false,
      capture_heatmaps: false,
      capture_exceptions: false,
      capture_performance: false,
      disable_surveys: true,
      disable_session_recording: true,
      persistence: "sessionStorage",
      save_referrer: false,
      save_campaign_params: false,
      ip: false,
      session_recording: {
        maskAllInputs: true,
        maskTextSelector: "*",
        blockSelector: "input, textarea, select, [contenteditable], .ph-no-capture",
      },
      before_send: (event) => {
        if (!event || !enabled()) return null;
        if (event.event === "$snapshot" && !window.location.pathname.startsWith("/articles/")) return null;
        // Scrub SDK-generated URL/referrer properties too, not just custom fields.
        for (const key of Object.keys(event.properties)) {
          if (/url|referrer/i.test(key)) delete event.properties[key];
        }
        event.properties.$current_url = window.location.origin + window.location.pathname;
        return event;
      },
    });
    client = posthog;
    return client;
  }).catch(() => { loading = undefined; return undefined; });
  return loading;
}

/** Send independently of GA4. A blocked SDK never delays navigation. */
export function capturePostHog(name: string, values: Record<string, string | number>) {
  if (!allowedEvents.has(name) || !enabled()) return;
  const path = window.location.pathname;
  void getPostHog().then((ph) => {
    if (!ph || window.location.pathname !== path) return;
    ph.capture(name, { ...posthogProperties(values), page_path: path });
  }).catch(() => {});
}

export function stopPostHogReplay() { client?.stopSessionRecording(); }
