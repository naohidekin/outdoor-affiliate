const pending: [string, Record<string, string | number>][] = [];
let awaitingInit = false;

/** Analytics must never interrupt navigation or the independent click beacon. */
export function trackEvent(name: string, parameters: Record<string, string | number>) {
  if (typeof window === "undefined") return;
  try {
    const gtag = (window as unknown as { gtag?: (...args: unknown[]) => void }).gtag;
    if (typeof gtag === "function") {
      gtag("event", name, parameters);
    } else {
      // Initial button observations can precede Next's afterInteractive script.
      // Wait for the site's existing GA configuration; don't create another tag.
      if (pending.length < 100) pending.push([name, parameters]);
      if (!awaitingInit) {
        awaitingInit = true;
        window.addEventListener("camp-analytics-ready", () => {
          awaitingInit = false;
          for (const [event, values] of pending.splice(0)) trackEvent(event, values);
        }, { once: true });
      }
    }
  } catch {
    // Navigation and purchase links remain usable if analytics is unavailable.
  }
}
