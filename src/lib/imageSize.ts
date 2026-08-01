// 表示枠に合ったサイズの画像URLを生成する。
// images.unoptimized: true 運用のため next/image は srcset を生成せず、
// 元URLのままだと48pxのサムネイル枠にも原寸（1500px等）が配信されていた。
// CDN側の公式リサイズ仕様をURLで指定して転送量とLCPを削る:
// - Amazon (m.media-amazon.com): ファイル名の修飾子を ._AC_SL{px}_ に置換
// - 楽天サムネイルプロキシ (thumbnail.image.rakuten.co.jp): ?_ex={px}x{px}
// - Unsplash (images.unsplash.com): w/h/q パラメータ（hはアスペクト比を維持して縮尺）
// それ以外（メーカー公式サイト等）はリサイズ仕様が不明なため原URLのまま返す
export function sizedImageUrl(url: string, px: number): string {
  if (!url || !url.startsWith("http")) return url;
  try {
    const u = new URL(url);

    if (u.hostname === "m.media-amazon.com") {
      return url.replace(
        /(?:\._[^/.]+_)?\.(jpg|jpeg|png|webp)(\?.*)?$/i,
        `._AC_SL${px}_.$1`
      );
    }

    if (u.hostname === "thumbnail.image.rakuten.co.jp") {
      u.search = `?_ex=${px}x${px}`;
      return u.toString();
    }

    if (u.hostname === "images.unsplash.com") {
      const w = Number(u.searchParams.get("w"));
      const h = Number(u.searchParams.get("h"));
      if (w && w > px) {
        if (h) u.searchParams.set("h", String(Math.round((h * px) / w)));
        u.searchParams.set("w", String(px));
      } else if (!w) {
        u.searchParams.set("w", String(px));
      }
      if (!u.searchParams.has("q")) u.searchParams.set("q", "75");
      return u.toString();
    }

    return url;
  } catch {
    return url;
  }
}
