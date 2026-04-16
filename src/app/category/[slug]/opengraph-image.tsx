import { ImageResponse } from "next/og";
import { getCategoryBySlug } from "@/lib/db";

export const alt = "Outdoor Gear Lab";
export const size = { width: 1200, height: 630 };
export const contentType = "image/png";

const CATEGORY_EMOJI: Record<string, string> = {
  tent: "⛺",
  light: "🔦",
  "sleeping-bag": "🛏️",
  burner: "🔥",
  backpack: "🎒",
  wear: "🧥",
  shoes: "🥾",
  firepit: "🔥",
  tarp: "🏕️",
  chair: "🪑",
  table: "🪵",
  cooler: "🧊",
};

async function loadNotoSansJP(): Promise<ArrayBuffer> {
  const css = await fetch(
    "https://fonts.googleapis.com/css2?family=Noto+Sans+JP:wght@700",
    { headers: { "User-Agent": "Mozilla/5.0 (compatible)" } }
  ).then((r) => r.text());
  const url = css.match(/src: url\((.+?)\)/)?.[1] ?? "";
  return fetch(url).then((r) => r.arrayBuffer());
}

export default async function Image({
  params,
}: {
  params: Promise<{ slug: string }>;
}) {
  const { slug } = await params;
  const category = await getCategoryBySlug(slug);
  const name = category?.name ?? slug;
  const emoji = CATEGORY_EMOJI[slug] ?? "🏕️";

  const fontData = await loadNotoSansJP();

  return new ImageResponse(
    (
      <div
        style={{
          width: "100%",
          height: "100%",
          display: "flex",
          flexDirection: "column",
          justifyContent: "center",
          alignItems: "center",
          background: "linear-gradient(135deg, #F5F0E8 0%, #E8DCC8 100%)",
          padding: "60px 80px",
          fontFamily: "NotoSansJP",
        }}
      >
        <span style={{ fontSize: "100px", marginBottom: "24px" }}>{emoji}</span>
        <div
          style={{
            fontSize: "52px",
            fontWeight: 700,
            color: "#1f2937",
            marginBottom: "16px",
            display: "flex",
          }}
        >
          {name}
        </div>
        <div
          style={{
            fontSize: "26px",
            color: "#78716c",
            marginBottom: "40px",
            display: "flex",
          }}
        >
          おすすめ比較・レビュー
        </div>
        <div
          style={{
            display: "flex",
            alignItems: "center",
            gap: "16px",
            position: "absolute",
            bottom: "40px",
          }}
        >
          <span style={{ fontSize: "36px" }}>🏕️</span>
          <span
            style={{
              fontSize: "28px",
              fontWeight: 700,
              color: "#92400e",
            }}
          >
            Outdoor Gear Lab
          </span>
          <span style={{ fontSize: "20px", color: "#78716c", marginLeft: "8px" }}>
            camp-gear-lab.com
          </span>
        </div>
      </div>
    ),
    {
      ...size,
      fonts: [{ name: "NotoSansJP", data: fontData, weight: 700 }],
    }
  );
}
