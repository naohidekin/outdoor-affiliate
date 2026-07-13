import { NextRequest, NextResponse } from "next/server";
import { getSupabase } from "@/lib/supabase";

export async function POST(req: NextRequest) {
  try {
    const body = await req.json();

    // 計測汚染対策: store はホワイトリスト、productId は形式検証、単純botは除外
    const ALLOWED_STORES = new Set(["amazon", "rakuten", "yahoo", "valuecommerce"]);
    const productId = typeof body.productId === "string" ? body.productId.trim() : "";
    const store = typeof body.store === "string" ? body.store : "";
    if (!productId || productId.length > 160 || /[\s<>"']/.test(productId) || !ALLOWED_STORES.has(store)) {
      return NextResponse.json({ error: "invalid" }, { status: 400 });
    }
    const uaRaw = req.headers.get("user-agent") || "";
    // 汎用の /bot/ は Cubot 等の実機UAに誤爆するため、既知のbotトークンのみ弾く
    if (/(googlebot|bingbot|yandex|baiduspider|duckduckbot|slurp|crawler|spider|headlesschrome|phantomjs|python-requests|python\/|curl\/|wget\/|axios\/|go-http-client|okhttp)/i.test(uaRaw)) {
      return NextResponse.json({ ok: true });
    }

    // placement はホワイトリスト検証（不正値は unknown に丸める）
    const ALLOWED_PLACEMENTS = new Set([
      "product_card", "ranking", "comparison_table",
      "recommended", "body_text", "unknown",
    ]);
    const placement = ALLOWED_PLACEMENTS.has(body.placement) ? body.placement : "unknown";
    const productName =
      typeof body.productName === "string" ? body.productName.slice(0, 200) : "";

    const entry = {
      product_id: productId,
      product_name: productName,
      store,
      placement,
      page_path: body.path || "",
      clicked_at: body.timestamp || new Date().toISOString(),
      ip: req.headers.get("x-forwarded-for")?.split(",")[0]?.trim() || "",
      ua: req.headers.get("user-agent")?.slice(0, 200) || "",
    };

    const supabase = getSupabase();
    const { error } = await supabase.from("affiliate_clicks").insert(entry);

    if (error) {
      console.error("[track-click] Supabase error:", error.message);
      return NextResponse.json({ ok: true });
    }

    return NextResponse.json({ ok: true });
  } catch {
    return NextResponse.json({ error: "failed" }, { status: 500 });
  }
}
