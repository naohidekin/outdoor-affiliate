import { NextRequest, NextResponse } from "next/server";
import { isAuthenticated } from "@/lib/auth";
import { google } from "googleapis";
import { getSupabase } from "@/lib/supabase";

function formatDate(d: Date): string {
  return d.toISOString().slice(0, 10);
}

interface ClickEntry {
  productId: string;
  store: string;
  path: string;
  timestamp: string;
}

async function readAffiliateClicks(startDate: string): Promise<ClickEntry[]> {
  try {
    const supabase = getSupabase();
    const { data } = await supabase
      .from("affiliate_clicks")
      .select("product_id, store, page_path, clicked_at")
      .gte("clicked_at", startDate);
    return (data || []).map((c) => ({
      productId: c.product_id,
      store: c.store,
      path: c.page_path,
      timestamp: c.clicked_at,
    }));
  } catch {
    return [];
  }
}

async function queryGA4(days: number) {
  const propertyId = process.env.GA4_PROPERTY_ID;
  if (!propertyId) return null;

  try {
    const credentials = JSON.parse(
      process.env.GOOGLE_CREDENTIALS || "{}"
    );
    const auth = new google.auth.GoogleAuth({
      credentials,
      scopes: ["https://www.googleapis.com/auth/analytics.readonly"],
    });
    const analyticsData = google.analyticsdata({ version: "v1beta", auth });

    const today = new Date();
    const start = new Date(today.getTime() - days * 24 * 60 * 60 * 1000);
    const dateRange = {
      startDate: formatDate(start),
      endDate: formatDate(today),
    };

    type GA4Row = { dimensionValues: Array<{ value: string }>; metricValues: Array<{ value: string }> };

    // X経由ソースフィルタ (x, t.co, twitter をまとめて扱う)
    const xSourceFilter = {
      filter: {
        fieldName: "sessionSource",
        inListFilter: {
          values: ["x", "t.co", "twitter"],
        },
      },
    };

    // 1. X経由日別トラフィック
    const byDayRes = await analyticsData.properties.runReport({
      property: `properties/${propertyId}`,
      requestBody: {
        dateRanges: [dateRange],
        dimensions: [{ name: "date" }],
        metrics: [
          { name: "screenPageViews" },
          { name: "sessions" },
        ],
        dimensionFilter: xSourceFilter,
        orderBys: [{ dimension: { dimensionName: "date" } }],
      },
    });

    // 2. X経由ページ別PV
    const byPageRes = await analyticsData.properties.runReport({
      property: `properties/${propertyId}`,
      requestBody: {
        dateRanges: [dateRange],
        dimensions: [{ name: "pagePath" }],
        metrics: [
          { name: "screenPageViews" },
          { name: "sessions" },
        ],
        dimensionFilter: {
          andGroup: {
            expressions: [
              xSourceFilter,
              {
                filter: {
                  fieldName: "pagePath",
                  stringFilter: {
                    matchType: "BEGINS_WITH",
                    value: "/articles/",
                  },
                },
              },
            ],
          },
        },
        orderBys: [
          { metric: { metricName: "screenPageViews" }, desc: true },
        ],
        limit: "20",
      },
    });

    // 3. 流入元別セッション
    const sourcesRes = await analyticsData.properties.runReport({
      property: `properties/${propertyId}`,
      requestBody: {
        dateRanges: [dateRange],
        dimensions: [{ name: "sessionSource" }],
        metrics: [{ name: "sessions" }],
        orderBys: [{ metric: { metricName: "sessions" }, desc: true }],
        limit: "10",
      },
    });

    const byDayRows = (byDayRes.data.rows || []) as GA4Row[];
    const byDay = byDayRows.map((r) => ({
      date: r.dimensionValues[0].value,
      pageViews: parseInt(r.metricValues[0].value || "0"),
      sessions: parseInt(r.metricValues[1].value || "0"),
    }));

    const byPageRows = (byPageRes.data.rows || []) as GA4Row[];
    const topPages = byPageRows.map((r) => ({
      path: r.dimensionValues[0].value,
      pageViews: parseInt(r.metricValues[0].value || "0"),
      sessions: parseInt(r.metricValues[1].value || "0"),
    }));

    const sourcesRows = (sourcesRes.data.rows || []) as GA4Row[];
    const sources = sourcesRows.map((r) => ({
      source: r.dimensionValues[0].value,
      sessions: parseInt(r.metricValues[0].value || "0"),
    }));

    const totalSessions = byDay.reduce((s, d) => s + d.sessions, 0);
    const totalPageViews = byDay.reduce((s, d) => s + d.pageViews, 0);

    return { totalSessions, totalPageViews, byDay, topPages, sources };
  } catch (err) {
    console.warn(`[x-analytics] GA4クエリ失敗: ${(err as Error).message}`);
    return null;
  }
}

export async function GET(req: NextRequest) {
  if (!(await isAuthenticated())) {
    return NextResponse.json({ error: "認証が必要です" }, { status: 401 });
  }

  const { searchParams } = new URL(req.url);
  const days = parseInt(searchParams.get("days") || "28", 10);
  const today = new Date();
  const start = new Date(today.getTime() - days * 24 * 60 * 60 * 1000);

  // GA4 data
  const ga4 = await queryGA4(days);

  // Affiliate clicks
  const clicks = await readAffiliateClicks(formatDate(start));
  const clicksByStore: Record<string, number> = {};
  const clicksByPage: Record<string, number> = {};
  const clicksByProduct: Record<string, { store: string; count: number }> = {};

  for (const c of clicks) {
    clicksByStore[c.store] = (clicksByStore[c.store] || 0) + 1;
    if (c.path) clicksByPage[c.path] = (clicksByPage[c.path] || 0) + 1;
    const key = `${c.productId}:${c.store}`;
    if (!clicksByProduct[key]) {
      clicksByProduct[key] = { store: c.store, count: 0 };
    }
    clicksByProduct[key].count++;
  }

  const topClickedPages = Object.entries(clicksByPage)
    .sort(([, a], [, b]) => b - a)
    .slice(0, 20)
    .map(([path, count]) => ({ path, clicks: count }));

  const topProducts = Object.entries(clicksByProduct)
    .sort(([, a], [, b]) => b.count - a.count)
    .slice(0, 10)
    .map(([key, v]) => ({
      productId: key.split(":")[0],
      store: v.store,
      count: v.count,
    }));

  // Cross-reference: GA4 topPages に affiliate clicks を付与
  const topPagesWithClicks = (ga4?.topPages || []).map((p: { path: string; pageViews: number; sessions: number }) => ({
    ...p,
    affiliateClicks: clicksByPage[p.path] || 0,
  }));

  return NextResponse.json({
    period: { start: formatDate(start), end: formatDate(today), days },
    xTraffic: ga4
      ? {
          totalSessions: ga4.totalSessions,
          totalPageViews: ga4.totalPageViews,
          byDay: ga4.byDay,
          topPages: topPagesWithClicks,
        }
      : null,
    affiliateClicks: {
      total: clicks.length,
      byStore: {
        amazon: clicksByStore["amazon"] || 0,
        rakuten: clicksByStore["rakuten"] || 0,
      },
      byPage: topClickedPages,
      topProducts,
    },
    trafficSources: ga4?.sources || [],
  });
}
