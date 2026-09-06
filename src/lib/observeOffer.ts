/** One observer for all merchant buttons. Collapsed/off-screen links don't count. */
const callbacks = new Map<Element, () => void>();
let observer: IntersectionObserver | undefined;

export function observeOffer(element: Element, onVisible: () => void): () => void {
  if (typeof IntersectionObserver === "undefined") return () => {};
  if (!observer) observer = new IntersectionObserver((entries) => {
    for (const entry of entries) {
      if (!entry.isIntersecting || entry.intersectionRatio < 0.5) continue;
      const callback = callbacks.get(entry.target);
      if (!callback) continue;
      callbacks.delete(entry.target);
      observer?.unobserve(entry.target);
      callback();
    }
  }, { threshold: 0.5 });
  callbacks.set(element, onVisible);
  observer.observe(element);
  return () => {
    callbacks.delete(element);
    observer?.unobserve(element);
    if (callbacks.size === 0) { observer?.disconnect(); observer = undefined; }
  };
}
