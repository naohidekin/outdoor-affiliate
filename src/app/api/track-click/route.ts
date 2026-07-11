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
    if (/bot|crawler|spider|headless|python|curl/i.test(uaRaw)) {
      return NextResponse.json({ ok: true });
    }

    const entry = {
      product_id: productId,
      store,
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
