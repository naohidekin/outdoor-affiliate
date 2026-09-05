import { NextRequest, NextResponse } from "next/server";
import { getSupabase } from "@/lib/supabase";
import { isAuthenticated } from "@/lib/auth";
import { aggregateAffiliateClicks, collectAffiliateClicks, type AffiliateClickRow } from "@/lib/affiliateAnalytics";

export const runtime = "nodejs";

export async function GET(req: NextRequest) {
  if (!(await isAuthenticated())) return NextResponse.json({ error: "認証が必要です" }, { status: 401 });
  const daysRaw = parseInt(req.nextUrl.searchParams.get("days") || "28", 10);
  const days = Math.min(365, Math.max(1, Number.isFinite(daysRaw) ? daysRaw : 28));
  const end = new Date().toISOString();
  const start = new Date(new Date(end).getTime() - days * 86400000).toISOString();
  try {
    const supabase = getSupabase();
    if (!supabase) throw new Error("Supabase is not configured");
    const [rows, articleResult, productResult] = await Promise.all([
      collectAffiliateClicks(async (afterId) => {
        const { data, error } = await supabase.from("affiliate_clicks")
          .select("id, product_id, store, page_path, clicked_at, placement")
          .gte("clicked_at", start).lt("clicked_at", end)
          .gt("id", afterId).order("id", { ascending: true }).limit(500);
        if (error) throw new Error(error.message);
        return (data ?? []) as AffiliateClickRow[];
      }),
      supabase.from("articles").select("slug, title"),
      supabase.from("products").select("id, name"),
    ]);
    if (articleResult.error || productResult.error) throw new Error("Could not load report labels");
    const titleBySlug = new Map<string, string>((articleResult.data ?? []).map((a) => [a.slug, a.title]));
    const nameById = new Map<string, string>((productResult.data ?? []).map((p) => [p.id, p.name]));
    return NextResponse.json({ period: { days, start, end }, ...aggregateAffiliateClicks(rows, titleBySlug, nameById) }, {
      headers: { "Cache-Control": "private, no-store" },
    });
  } catch (error) {
    console.error("[affiliate-analytics]", error instanceof Error ? error.message : "Report failed");
    return NextResponse.json({ error: "集計を取得できませんでした。期間を短くするか、時間をおいて再試行してください。" }, { status: 503 });
  }
}
