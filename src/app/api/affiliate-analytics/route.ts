import { NextRequest, NextResponse } from "next/server";
import { getSupabase } from "@/lib/supabase";
import { isAuthenticated } from "@/lib/auth";

export const runtime = "nodejs";

type ClickRow = { product_id: string; store: string; page_path: string; clicked_at: string };
type Agg = { clicks: number; stores: Record<string, number> };

function bump(map: Record<string, Agg>, key: string, store: string) {
  if (!map[key]) map[key] = { clicks: 0, stores: {} };
  map[key].clicks += 1;
  map[key].stores[store] = (map[key].stores[store] || 0) + 1;
}

export async function GET(req: NextRequest) {
  if (!(await isAuthenticated())) {
    return NextResponse.json({ error: "認証が必要です" }, { status: 401 });
  }

  const daysRaw = parseInt(req.nextUrl.searchParams.get("days") || "28", 10);
  const days = Math.min(365, Math.max(1, Number.isFinite(daysRaw) ? daysRaw : 28));
  const start = new Date(Date.now() - days * 86400000).toISOString();

  const supabase = getSupabase();
  if (!supabase) {
    return NextResponse.json({ error: "supabase not configured" }, { status: 500 });
  }

  const [{ data: clicks }, { data: arts }, { data: prods }] = await Promise.all([
    supabase
      .from("affiliate_clicks")
      .select("product_id, store, page_path, clicked_at")
      .gte("clicked_at", start),
    supabase.from("articles").select("slug, title"),
    supabase.from("products").select("id, name"),
  ]);

  const titleBySlug = new Map<string, string>((arts || []).map((a) => [a.slug, a.title]));
  const nameById = new Map<string, string>((prods || []).map((p) => [p.id, p.name]));

  const rows = (clicks || []) as ClickRow[];
  const byStore: Record<string, number> = {};
  const byArticle: Record<string, Agg> = {};
  const byProduct: Record<string, Agg> = {};

  for (const c of rows) {
    const store = c.store || "other";
    byStore[store] = (byStore[store] || 0) + 1;
    bump(byArticle, c.page_path || "(不明)", store);
    bump(byProduct, c.product_id || "(不明)", store);
  }

  const articleRanking = Object.entries(byArticle)
    .map(([path, v]) => {
      const slug = path.replace(/^\/articles\//, "").replace(/\/$/, "");
      return { path, title: titleBySlug.get(slug) || path, clicks: v.clicks, stores: v.stores };
    })
    .sort((a, b) => b.clicks - a.clicks);

  const productRanking = Object.entries(byProduct)
    .map(([productId, v]) => ({
      productId,
      name: nameById.get(productId) || productId,
      clicks: v.clicks,
      stores: v.stores,
    }))
    .sort((a, b) => b.clicks - a.clicks);

  return NextResponse.json({
    period: { days, start },
    total: rows.length,
    byStore,
    articleRanking,
    productRanking,
  });
}
