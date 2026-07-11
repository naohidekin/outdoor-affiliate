import fs from "node:fs/promises";
import path from "node:path";
import { NextRequest, NextResponse } from "next/server";
import { isAuthenticated } from "@/lib/auth";

export const runtime = "nodejs";

const HOME = process.env.HOME || "";
const POSTS_PATH = path.join(
  HOME,
  "Desktop/AI関連/note-dr-auto/data/x-posts.json",
);

type DrAutoStatus = "draft" | "approved" | "posted" | "rejected";

type DrAutoPost = {
  id: string;
  type: string;
  pipeline_id: string | null;
  body: string;
  status: DrAutoStatus;
  scores?: Record<string, number> | null;
  avgScore?: number | null;
  generated_at: string;
  posted_at: string | null;
  tweet_id: string | null;
};

async function readPosts(): Promise<DrAutoPost[]> {
  try {
    const raw = await fs.readFile(POSTS_PATH, "utf8");
    return JSON.parse(raw) as DrAutoPost[];
  } catch {
    return [];
  }
}

export async function GET() {
  if (!(await isAuthenticated())) {
    return NextResponse.json({ error: "認証が必要です" }, { status: 401 });
  }
  try {
    return NextResponse.json(await readPosts());
  } catch (error) {
    console.error("drAuto posts GET error:", error);
    return NextResponse.json({ error: "取得失敗" }, { status: 500 });
  }
}

export async function PATCH(req: NextRequest) {
  if (!(await isAuthenticated())) {
    return NextResponse.json({ error: "認証が必要です" }, { status: 401 });
  }
  try {
    const body = (await req.json()) as { id?: string; status?: DrAutoStatus };
    if (!body.id || !body.status) {
      return NextResponse.json({ error: "id と status が必要です" }, { status: 400 });
    }
    const posts = await readPosts();
    const idx = posts.findIndex((p) => p.id === body.id);
    if (idx === -1) {
      return NextResponse.json({ error: "Not found" }, { status: 404 });
    }
    posts[idx] = { ...posts[idx], status: body.status };
    await fs.writeFile(POSTS_PATH, `${JSON.stringify(posts, null, 2)}\n`, "utf8");
    return NextResponse.json(posts[idx]);
  } catch (error) {
    console.error("drAuto posts PATCH error:", error);
    return NextResponse.json({ error: "更新失敗" }, { status: 500 });
  }
}
