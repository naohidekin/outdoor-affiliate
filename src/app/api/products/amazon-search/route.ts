import { NextRequest, NextResponse } from "next/server";
import { isAuthenticated } from "@/lib/auth";
import { searchItems, extractAsin } from "@/lib/amazon-pa-api";
import { getProducts } from "@/lib/db";

/**
 * Amazonキーワード検索で新商品を発見
 * GET /api/products/amazon-search?q=テント&browseNodeId=（省略可）
 */
export async function GET(request: NextRequest) {
  if (!(await isAuthenticated())) {
    return NextResponse.json({ error: "認証が必要です" }, { status: 401 });
  }

  const { searchParams } = new URL(request.url);
  const q = searchParams.get("q");
  const browseNodeId = searchParams.get("browseNodeId") ?? undefined;

  if (!q) {
    return NextResponse.json({ error: "検索キーワード(q)が必要です" }, { status: 400 });
  }

  const [items, existing] = await Promise.all([
    searchItems(q, browseNodeId),
    getProducts(),
  ]);

  const existingAsins = new Set(
    existing.map((p) => extractAsin(p.amazonUrl || "")).filter(Boolean)
  );

  const results = items.map((item) => ({
    ...item,
    amazonUrl: `https://www.amazon.co.jp/dp/${item.asin}/?tag=${process.env.AMAZON_PARTNER_TAG || "camp78-22"}`,
    isNew: !existingAsins.has(item.asin),
  }));

  return NextResponse.json({ results, total: results.length });
}
