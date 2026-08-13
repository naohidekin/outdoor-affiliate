import { NextRequest, NextResponse } from "next/server";
import { createHash } from "crypto";
import { getSupabase } from "@/lib/supabase";
import { AFFILIATE_PLACEMENTS } from "@/lib/trackAffiliateClick";
import { getProducts } from "@/lib/db";

// 記事本文のリンク（BodyLink）は商品IDを持たないため "inline" を送ってくる。
// そのままだと週30件前後のクリックがどの商品か分からず、記事本文の
// 導線改善が効いたかを商品単位で測れない（2026-08-13に判明）。
// ビーコンには link_url が含まれているので、リンク先から商品を逆引きする。
const INLINE_SENTINEL = "inline";

let linkIndex: Map<string, { id: string; name: string }> | null = null;
let linkIndexAt = 0;
const INDEX_TTL_MS = 10 * 60 * 1000;

/** リンク先を一意に指す部分だけを取り出す（ASIN / 楽天の店舗＋商品コード） */
function linkKey(url: string): string | null {
  let u = url;
  try {
    u = decodeURIComponent(url);
  } catch {
    /* エンコードが壊れていてもそのまま試す */
  }
  const asin = u.match(/\/(?:dp|gp\/product)\/([A-Z0-9]{10})/i);
  if (asin) return `amazon:${asin[1].toUpperCase()}`;
  const rakuten = u.match(/item\.rakuten\.co\.jp\/([^/]+)\/([^/?&]+)/);
  if (rakuten) return `rakuten:${rakuten[1]}/${rakuten[2]}`;
  const rakutenCatalog = u.match(/product\.rakuten\.co\.jp\/product\/-\/([A-Za-z0-9]+)/);
  if (rakutenCatalog) return `rakuten-catalog:${rakutenCatalog[1]}`;
  // 検索ページ行きのリンクは指す商品が定まらないので逆引きしない
  return null;
}

async function resolveProductByLink(url: string) {
  if (!url) return null;
  const key = linkKey(url);
  if (!key) return null;
  if (!linkIndex || Date.now() - linkIndexAt > INDEX_TTL_MS) {
    try {
      const products = await getProducts();
      const idx = new Map<string, { id: string; name: string }>();
      for (const p of products) {
        for (const candidate of [p.affiliateUrl, p.amazonUrl]) {
          const k = candidate ? linkKey(candidate) : null;
          // 同じリンクを複数商品が持つ場合は先勝ち（重複登録は別途整理中）
          if (k && !idx.has(k)) idx.set(k, { id: p.id, name: p.name });
        }
      }
      linkIndex = idx;
      linkIndexAt = Date.now();
    } catch {
      return null; // 逆引きできなくても計測そのものは続ける
    }
  }
  return linkIndex.get(key) ?? null;
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
