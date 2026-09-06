export interface AffiliateClickRow {
  id: number; product_id: string; store: string; page_path: string;
  clicked_at: string; placement?: string | null;
}

/** Keyset pagination: don't mistake a provider's row limit for the full period. */
export async function collectAffiliateClicks(fetchPage: (afterId: number) => Promise<AffiliateClickRow[]>) {
  const rows: AffiliateClickRow[] = [];
  let cursor = 0;
  for (let page = 0; page < 200; page++) {
    const batch = await fetchPage(cursor);
    if (!batch.length) return rows;
    for (const row of batch) {
      if (!Number.isSafeInteger(row.id) || row.id <= cursor) throw new Error("Invalid click pagination cursor");
      cursor = row.id;
      rows.push(row);
    }
  }
  throw new Error("Click report is too large; select a shorter period");
}

type Aggregate = { clicks: number; stores: Record<string, number> };
const counts = (): Record<string, number> => Object.create(null);
function bump(map: Map<string, Aggregate>, key: string, store: string) {
  const aggregate = map.get(key) ?? { clicks: 0, stores: counts() };
  aggregate.clicks++;
  aggregate.stores[store] = (aggregate.stores[store] ?? 0) + 1;
  map.set(key, aggregate);
}

export function aggregateAffiliateClicks(rows: AffiliateClickRow[], titleBySlug: Map<string, string>, nameById: Map<string, string>) {
  const byStore = counts(), byPlacement = counts();
  const byArticle = new Map<string, Aggregate>(), byProduct = new Map<string, Aggregate>();
  const byJourney = new Map<string, Aggregate>();
  const safePath = (path: string) => /^\/(?!\/)/.test(path) && !/[\\\s<>]/.test(path) ? path.split(/[?#]/)[0] : "";
  const titleFor = (path: string) => path === "/" ? "トップページ" : path === "/gear-guides" ? "目的別ギアガイド" : titleBySlug.get(path.replace(/^\/articles\//, "").replace(/\/$/, "")) || path || "ページ不明";
  for (const row of rows) {
    const store = row.store || "other", placement = row.placement || "(計測前)";
    const path = safePath(row.page_path ?? ""), productId = row.product_id || "(不明)";
    byStore[store] = (byStore[store] ?? 0) + 1;
    byPlacement[placement] = (byPlacement[placement] ?? 0) + 1;
    bump(byArticle, path, store); bump(byProduct, productId, store);
    bump(byJourney, JSON.stringify([path, productId, placement]), store);
  }
  const descending = (a: Aggregate, b: Aggregate) => b.clicks - a.clicks;
  return {
    total: rows.length, byStore, byPlacement,
    articleRanking: [...byArticle].map(([path, value]) => ({ path, title: titleFor(path), ...value })).sort(descending),
    productRanking: [...byProduct].map(([productId, value]) => ({ productId, name: nameById.get(productId) || productId, ...value })).sort(descending),
    journeyRanking: [...byJourney].map(([key, value]) => {
      const [path, productId, placement] = JSON.parse(key) as string[];
      return { path, title: titleFor(path), productId, name: nameById.get(productId) || productId, placement, ...value };
    }).sort(descending),
  };
}
