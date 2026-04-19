import { NextResponse } from "next/server";
import fs from "fs";
import path from "path";

export const dynamic = "force-dynamic";

export async function GET() {
  try {
    const dir = path.join(process.cwd(), "public", "images", "4koma");
    if (!fs.existsSync(dir)) return NextResponse.json({ files: [] });

    const files = fs.readdirSync(dir)
      .filter((f: string) => f.endsWith(".png"))
      .map((f: string) => {
        const stat = fs.statSync(path.join(dir, f));
        return { name: f, path: `/images/4koma/${f}`, createdAt: stat.mtime.toISOString() };
      })
      .sort((a: { createdAt: string }, b: { createdAt: string }) => new Date(b.createdAt).getTime() - new Date(a.createdAt).getTime())
      .slice(0, 30);

    return NextResponse.json({ files });
  } catch {
    return NextResponse.json({ files: [] });
  }
}
