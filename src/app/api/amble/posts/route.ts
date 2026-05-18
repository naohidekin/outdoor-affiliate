import fs from "node:fs/promises";
import path from "node:path";
import { NextRequest, NextResponse } from "next/server";
import { isAuthenticatedRequest } from "@/lib/auth";

export const runtime = "nodejs";

const HOME = process.env.HOME || "";
const AMBLE_POSTS_PATH = path.join(HOME, "Desktop/AI関連/claude/san-pedinvestor-x/data/x-posts.json");

type AmbleStatus = "draft" | "approved" | "posted" | "skip" | "rejected";

type AmblePost = {
  id: string;
  text: string;
  status: AmbleStatus;
  score_a?: number | null;
  score_b?: number | null;
  score_c?: number | null;
  score_d?: number | null;
  score_ai?: number | null;
};

async function readPosts(): Promise<AmblePost[]> {
  const raw = await fs.readFile(AMBLE_POSTS_PATH, "utf8");
  return JSON.parse(raw) as AmblePost[];
}

export async function GET(req: NextRequest) {
  if (!isAuthenticatedRequest(req)) {
    return NextResponse.json({ error: "認証が必要です" }, { status: 401 });
  }

  try {
    const posts = await readPosts();
    return NextResponse.json(posts);
  } catch (error) {
    console.error("Amble posts GET error:", error);
    return NextResponse.json({ error: "データ取得に失敗しました" }, { status: 500 });
  }
}

export async function PATCH(req: NextRequest) {
  if (!isAuthenticatedRequest(req)) {
    return NextResponse.json({ error: "認証が必要です" }, { status: 401 });
  }

  try {
    const body = (await req.json()) as { id?: string; status?: AmbleStatus };
    if (!body.id || !body.status) {
      return NextResponse.json({ error: "id と status が必要です" }, { status: 400 });
    }

    const posts = await readPosts();
    const index = posts.findIndex((post) => post.id === body.id);
    if (index === -1) {
      return NextResponse.json({ error: "Not found" }, { status: 404 });
    }

    const updated = { ...posts[index], status: body.status };
    posts[index] = updated;
    await fs.writeFile(AMBLE_POSTS_PATH, `${JSON.stringify(posts, null, 2)}\n`, "utf8");

    return NextResponse.json(updated);
  } catch (error) {
    console.error("Amble posts PATCH error:", error);
    return NextResponse.json({ error: "更新に失敗しました" }, { status: 500 });
  }
}

export async function DELETE(req: NextRequest) {
  if (!isAuthenticatedRequest(req)) {
    return NextResponse.json({ error: "認証が必要です" }, { status: 401 });
  }

  try {
    const body = (await req.json()) as { id?: string };
    if (!body.id) {
      return NextResponse.json({ error: "id が必要です" }, { status: 400 });
    }

    const posts = await readPosts();
    const index = posts.findIndex((post) => post.id === body.id);
    if (index === -1) {
      return NextResponse.json({ error: "Not found" }, { status: 404 });
    }

    const deleted = posts[index];
    posts.splice(index, 1);
    await fs.writeFile(AMBLE_POSTS_PATH, `${JSON.stringify(posts, null, 2)}\n`, "utf8");

    return NextResponse.json({ success: true, deleted });
  } catch (error) {
    console.error("Amble posts DELETE error:", error);
    return NextResponse.json({ error: "削除に失敗しました" }, { status: 500 });
  }
}
