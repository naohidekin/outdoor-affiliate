import { NextRequest, NextResponse } from "next/server";
import { isAuthenticated } from "@/lib/auth";
import { getProducts, saveProduct } from "@/lib/db";
import { batchGetItems, extractAsin } from "@/lib/amazon-pa-api";

/** 全商品の価格・在庫をPA-APIで同期 */
export async function GET(request: NextRequest) {
  if (!(await isAuthenticated())) {
    return NextResponse.json({ error: "認証が必要です" }, { status: 401 });
  }

  const { searchParams } = new URL(request.url);
  // 注意: 10件/バッチ・1.1秒間隔のため、136 ASINで約14秒かかる。
  // Vercel Hobby plan は10秒制限のため、本番ではlimitを小さくするか分割実行すること。
  const limit = Math.min(parseInt(searchParams.get("limit") || "10"), 200);

  const products = await getProducts();
  const targets = products
    .filter((p) => !!extractAsin(p.amazonUrl || ""))
    .slice(0, limit);

  const asins = targets.map((p) => extractAsin(p.amazonUrl)!);

  const amazonData = await batchGetItems(asins);
  const asinMap = new Map(amazonData.map((item) => [item.asin, item]));

  let updated = 0;
  const changes: { id: string; name: string; oldPrice: number; newPrice: number }[] = [];

  for (const product of targets) {
    const asin = extractAsin(product.amazonUrl);
    if (!asin) continue;
    const data = asinMap.get(asin);
    if (!data) continue;

    const newPrice = data.price ?? product.price;
    const priceChanged = newPrice !== product.price;

    if (priceChanged || product.availability !== data.availability) {
      if (priceChanged) {
        changes.push({ id: product.id, name: product.name, oldPrice: product.price, newPrice });
      }
      await saveProduct({
        ...product,
        price: newPrice,
        availability: data.availability,
        updatedAt: new Date().toISOString(),
      });
      updated++;
    }
  }

  return NextResponse.json({ synced: updated, total: targets.length, changes });
}

/** 指定ASIN配列のみ同期 */
export async function POST(request: NextRequest) {
  if (!(await isAuthenticated())) {
    return NextResponse.json({ error: "認証が必要です" }, { status: 401 });
  }

  const { asins } = await request.json() as { asins: string[] };
  if (!Array.isArray(asins) || asins.length === 0) {
    return NextResponse.json({ error: "asins配列が必要です" }, { status: 400 });
  }

  const products = await getProducts();
  const amazonData = await batchGetItems(asins);
  const asinMap = new Map(amazonData.map((item) => [item.asin, item]));

  let updated = 0;
  for (const product of products) {
    const asin = extractAsin(product.amazonUrl || "");
    if (!asin || !asins.includes(asin)) continue;
    const data = asinMap.get(asin);
    if (!data) continue;
    await saveProduct({
      ...product,
      price: data.price ?? product.price,
      availability: data.availability,
      updatedAt: new Date().toISOString(),
    });
    updated++;
  }

  return NextResponse.json({ synced: updated, results: amazonData });
}
