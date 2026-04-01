import { ImageResponse } from "next/og";
import { getArticleBySlug, getCategoryById } from "@/lib/db";

export const alt = "Outdoor Gear Lab";
export const size = { width: 1200, height: 630 };
export const contentType = "image/png";

export default async function Image({
  params,
}: {
  params: Promise<{ slug: string }>;
}) {
  const { slug } = await params;
  const article = getArticleBySlug(slug);
  const category = article ? getCategoryById(article.categoryId) : null;

  const title = article?.title ?? "Outdoor Gear Lab";
  const categoryName = category?.name ?? "";

  return new ImageResponse(
    (
      <div
        style={{
          width: "100%",
          height: "100%",
          display: "flex",
          flexDirection: "column",
          justifyContent: "center",
          background: "linear-gradient(135deg, #F5F0E8 0%, #E8DCC8 100%)",
          padding: "60px 80px",
          fontFamily: "sans-serif",
        }}
      >
        {categoryName && (
          <div
            style={{
              display: "flex",
              alignItems: "center",
              marginBottom: "24px",
            }}
          >
            <span
              style={{
                background: "#92400e",
                color: "white",
                padding: "8px 20px",
                borderRadius: "9999px",
                fontSize: "24px",
                fontWeight: 700,
              }}
            >
              {categoryName}
            </span>
          </div>
        )}
        <div
          style={{
            fontSize: title.length > 40 ? "42px" : "52px",
            fontWeight: 700,
            color: "#1f2937",
            lineHeight: 1.4,
            maxWidth: "1000px",
            display: "flex",
          }}
        >
          {title}
        </div>
        <div
          style={{
            display: "flex",
            alignItems: "center",
            marginTop: "auto",
            gap: "16px",
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
    { ...size }
  );
}
