import { ImageResponse } from "next/og";
import { getArticleBySlug, getCategoryById } from "@/lib/db";

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
  const article = await getArticleBySlug(slug);
  const category = article ? await getCategoryById(article.categoryId) : null;

  const title = article?.title ?? "Outdoor Gear Lab";
  const categoryName = category?.name ?? "";
  const categorySlug = category?.slug ?? "";
  const emoji = CATEGORY_EMOJI[categorySlug] ?? "🏕️";

  const fontData = await loadNotoSansJP();

  return new ImageResponse(
    (
      <div
        style={{
          width: "100%",
          height: "100%",
          display: "flex",
          flexDirection: "column",
          background: "linear-gradient(160deg, #1a2e1a 0%, #2d4a1e 40%, #3d5a28 100%)",
          fontFamily: "NotoSansJP",
          position: "relative",
          overflow: "hidden",
        }}
      >
        {/* 装飾パターン */}
        <div
          style={{
            position: "absolute",
            top: "-60px",
            right: "-60px",
            width: "300px",
            height: "300px",
            borderRadius: "50%",
            background: "rgba(255,255,255,0.04)",
            display: "flex",
          }}
        />
        <div
          style={{
            position: "absolute",
            bottom: "-80px",
            left: "-40px",
            width: "250px",
            height: "250px",
            borderRadius: "50%",
            background: "rgba(255,255,255,0.03)",
            display: "flex",
          }}
        />

        {/* メインコンテンツ */}
        <div
          style={{
            display: "flex",
            flexDirection: "column",
            justifyContent: "center",
            padding: "60px 80px",
            flex: 1,
          }}
        >
          {/* カテゴリバッジ */}
          {categoryName && (
            <div
              style={{
                display: "flex",
                alignItems: "center",
                marginBottom: "28px",
              }}
            >
              <span
                style={{
                  background: "rgba(251, 191, 36, 0.9)",
                  color: "#1a2e1a",
                  padding: "10px 24px",
                  borderRadius: "9999px",
                  fontSize: "22px",
                  fontWeight: 700,
                  display: "flex",
                  alignItems: "center",
                  gap: "8px",
                }}
              >
                {emoji} {categoryName}
              </span>
            </div>
          )}

          {/* タイトル */}
          <div
            style={{
              fontSize: title.length > 30 ? (title.length > 45 ? "38px" : "44px") : "52px",
              fontWeight: 700,
              color: "#ffffff",
              lineHeight: 1.5,
              maxWidth: "1000px",
              display: "flex",
              textShadow: "0 2px 4px rgba(0,0,0,0.3)",
            }}
          >
            {title}
          </div>
        </div>

        {/* フッター */}
        <div
          style={{
            display: "flex",
            alignItems: "center",
            justifyContent: "space-between",
            padding: "0 80px 40px",
          }}
        >
          <div
            style={{
              display: "flex",
              alignItems: "center",
              gap: "12px",
            }}
          >
            <span style={{ fontSize: "32px" }}>🏕️</span>
            <span
              style={{
                fontSize: "26px",
                fontWeight: 700,
                color: "#fbbf24",
              }}
            >
              Outdoor Gear Lab
            </span>
          </div>
          <span style={{ fontSize: "18px", color: "rgba(255,255,255,0.5)" }}>
            camp-gear-lab.com
          </span>
        </div>

        {/* 下部アクセントライン */}
        <div
          style={{
            height: "6px",
            background: "linear-gradient(90deg, #fbbf24 0%, #f59e0b 50%, #fbbf24 100%)",
            display: "flex",
          }}
        />
      </div>
    ),
    {
      ...size,
      fonts: [{ name: "NotoSansJP", data: fontData, weight: 700 }],
    }
  );
}
