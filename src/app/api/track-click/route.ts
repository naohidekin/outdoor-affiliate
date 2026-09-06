import { NextRequest, NextResponse } from "next/server";
import { createHash } from "crypto";
import { getSupabase } from "@/lib/supabase";
import { AFFILIATE_PLACEMENTS } from "@/lib/trackAffiliateClick";
import { getTrackingProducts } from "@/lib/db";
import { buildAffiliateProductIndex, resolveAffiliateProduct, type AffiliateProduct } from "@/lib/affiliateProduct";

// 旧ページから送られる inline は、現在の本文リンクと共通のロジックで解決する。
const INLINE_SENTINEL = "inline";

let linkIndex: Map<string, AffiliateProduct | null> | null = null;
let linkIndexAt = 0;
const INDEX_TTL_MS = 10 * 60 * 1000;

// Compatibility for already-open pages that still send the legacy sentinel.
async function resolveProductByLink(url: string) {
  if (!linkIndex || Date.now() - linkIndexAt > INDEX_TTL_MS) {
    try {
      linkIndex = buildAffiliateProductIndex(await getTrackingProducts());
      linkIndexAt = Date.now();
    } catch { return null; }
  }
  return resolveAffiliateProduct(url, linkIndex);
}

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

    // placement はホワイトリスト検証（不正値は unknown に丸める）。
    // リストはクライアントと共通定義（別管理だと追加漏れでunknownに丸められる）
    const ALLOWED_PLACEMENTS = new Set<string>(AFFILIATE_PLACEMENTS);
    const placement = ALLOWED_PLACEMENTS.has(body.placement) ? body.placement : "unknown";
    let resolvedId = productId;
    let productName =
      typeof body.productName === "string" ? body.productName.slice(0, 200) : "";

    // 本文リンクはリンク先から商品を特定する。引けなければ "inline" のまま残す
    if (productId === INLINE_SENTINEL) {
      const hit = await resolveProductByLink(
        typeof body.link_url === "string" ? body.link_url : ""
      );
      if (hit) {
        resolvedId = hit.id;
        if (!productName) productName = hit.name.slice(0, 200);
      }
    }

    // IPは生値を保存せず、日替わりソルト付きハッシュに置き換える。
    // 用途は同日内の重複クリック排除だけなので、翌日以降に個人を追跡できる
    // 必要はなく、保存期間に関わらず個人特定性を落としておく
    const rawIp = req.headers.get("x-forwarded-for")?.split(",")[0]?.trim() || "";
    const day = new Date().toISOString().slice(0, 10);
    const ipHash = rawIp
      ? createHash("sha256").update(`${day}:${rawIp}`).digest("hex").slice(0, 32)
      : "";

    const entry = {
      product_id: resolvedId,
      product_name: productName,
      store,
      placement,
      page_path: typeof body.path === "string" ? body.path.slice(0, 300) : "",
      // クライアントの時刻は改ざん・時計ずれがあるためサーバー時刻を正とする
      clicked_at: new Date().toISOString(),
      ip: ipHash,
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
