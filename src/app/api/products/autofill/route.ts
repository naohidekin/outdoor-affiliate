import { NextRequest, NextResponse } from "next/server";
import { isAuthenticated } from "@/lib/auth";
import { getItemsByAsins, extractAsin } from "@/lib/amazon-pa-api";

/**
 * ASINから商品データを自動補完
 * POST { asin: string } or { url: string }
 */
export async function POST(request: NextRequest) {
  if (!(await isAuthenticated())) {
    return NextResponse.json({ error: "認証が必要です" }, { status: 401 });
  }

  const body = await request.json() as { asin?: string; url?: string };
  let asin = body.asin;

  if (!asin && body.url) {
    asin = extractAsin(body.url) ?? undefined;
  }

  if (!asin || !/^[A-Z0-9]{10}$/.test(asin)) {
    return NextResponse.json({ error: "有効なASINが必要です" }, { status: 400 });
  }

  const items = await getItemsByAsins([asin]);
  if (items.length === 0) {
    return NextResponse.json({ error: "商品が見つかりませんでした" }, { status: 404 });
  }

  const item = items[0];
  return NextResponse.json({
    asin: item.asin,
    name: item.title,
    brand: item.brand,
    price: item.price,
    imageUrl: item.imageUrl,
    availability: item.availability,
    features: item.features,
    amazonUrl: `https://www.amazon.co.jp/dp/${item.asin}/?tag=${process.env.AMAZON_PARTNER_TAG || "camp78-22"}`,
  });
}
