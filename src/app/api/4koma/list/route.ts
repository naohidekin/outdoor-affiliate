import { NextResponse } from "next/server";
import { list } from "@vercel/blob";
import fs from "fs";
import path from "path";

export const dynamic = "force-dynamic";

interface FileItem {
  name: string;
  path: string;
  createdAt: string;
}

/**
 * 4コマ漫画とキーイラストの過去生成画像一覧。
 *
 * 優先順位:
 *   1. Vercel Blob (BLOB_READ_WRITE_TOKEN がある場合) — 本番運用
 *   2. ローカル public/images/4koma/ — npm run dev でのローカル運用
 */
export async function GET() {
  const hasBlobToken = !!process.env.BLOB_READ_WRITE_TOKEN;

  if (hasBlobToken) {
    try {
      const blobItems: FileItem[] = [];
      for (const prefix of ["4koma-", "keyvisual-"]) {
        const { blobs } = await list({ prefix });
        for (const b of blobs) {
          blobItems.push({
            name: b.pathname,
            path: b.url,
            createdAt:
              b.uploadedAt instanceof Date
                ? b.uploadedAt.toISOString()
                : String(b.uploadedAt),
          });
        }
      }
      blobItems.sort(
        (a, b) =>
          new Date(b.createdAt).getTime() - new Date(a.createdAt).getTime()
      );
      return NextResponse.json({ files: blobItems.slice(0, 30) });
    } catch (err) {
      console.warn("[4koma list] Blob read失敗、ローカルfallbackします:", err);
    }
  }

  // ローカル fallback（dev環境用）
  try {
    const dir = path.join(process.cwd(), "public", "images", "4koma");
    if (!fs.existsSync(dir)) return NextResponse.json({ files: [] });

    const files = fs
      .readdirSync(dir)
      .filter((f: string) => f.endsWith(".png"))
      .map((f: string) => {
        const stat = fs.statSync(path.join(dir, f));
        return {
          name: f,
          path: `/images/4koma/${f}`,
          createdAt: stat.mtime.toISOString(),
        };
      })
      .sort(
        (a: { createdAt: string }, b: { createdAt: string }) =>
          new Date(b.createdAt).getTime() - new Date(a.createdAt).getTime()
      )
      .slice(0, 30);

    return NextResponse.json({ files });
  } catch {
    return NextResponse.json({ files: [] });
  }
}
