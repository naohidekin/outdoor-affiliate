import { ImageResponse } from "next/og";

export const alt = "Camp Gear Lab - アウトドア用品比較・レビュー";
export const size = { width: 1200, height: 630 };
export const contentType = "image/png";

export default async function Image() {
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
          background: "linear-gradient(135deg, #0f172a 0%, #1e3a5f 50%, #0f172a 100%)",
          padding: "60px 80px",
          fontFamily: "sans-serif",
        }}
      >
        <span style={{ fontSize: "80px", marginBottom: "24px" }}>🏕️</span>
        <div
          style={{
            fontSize: "56px",
            fontWeight: 700,
            color: "#ffffff",
            marginBottom: "16px",
            display: "flex",
          }}
        >
          Camp Gear Lab
        </div>
        <div
          style={{
            fontSize: "28px",
            color: "#93c5fd",
            marginBottom: "40px",
            display: "flex",
          }}
        >
          アウトドア用品を徹底比較・レビュー
        </div>
        <div
          style={{
            display: "flex",
            gap: "24px",
          }}
        >
          {["テント", "シュラフ", "バーナー", "チェア", "焚き火台"].map(
            (item) => (
              <span
                key={item}
                style={{
                  background: "rgba(255,255,255,0.15)",
                  color: "#ffffff",
                  padding: "10px 24px",
                  borderRadius: "9999px",
                  fontSize: "22px",
                  fontWeight: 600,
                }}
              >
                {item}
              </span>
            )
          )}
        </div>
        <div
          style={{
            position: "absolute",
            bottom: "40px",
            fontSize: "20px",
            color: "#7dd3fc",
            display: "flex",
          }}
        >
          camp-gear-lab.com
        </div>
      </div>
    ),
    { ...size }
  );
}
