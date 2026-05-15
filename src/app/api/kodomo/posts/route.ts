import fs from "node:fs/promises";
import path from "node:path";
import { NextRequest, NextResponse } from "next/server";
import { isAuthenticatedRequest } from "@/lib/auth";

export const runtime = "nodejs";

const HOME = process.env.HOME || "";
const KODOMO_POSTS_PATH = path.join(HOME, "Desktop/AI関連/parent-child-medical/data/x/posts.jsonl");

type KodomoStatus = "reviewed" | "approved" | "posted" | "rejected" | "dead_letter";

type KodomoPost = {
  id: string;
  body: string;
  status: KodomoStatus;
  humanApprovedBy?: string | null;
  humanApprovedAt?: string | null;
  claimRisk?: string | null;
  score?: number | null;
  _scores?: Record<string, number | null | undefined>;
};

async function readPosts(): Promise<KodomoPost[]> {
  const raw = await fs.readFile(KODOMO_POSTS_PATH, "utf8");
  return raw
    .split("\n")
    .filter((line) => line.trim())
    .map((line) => JSON.parse(line) as KodomoPost);
}

export async function GET(req: NextRequest) {
  if (!isAuthenticatedRequest(req)) {
    return NextResponse.json({ error: "認証が必要です" }, { status: 401 });
  }

  try {
    const posts = await readPosts();
    return NextResponse.json(posts);
  } catch (error) {
    console.error("Kodomo posts GET error:", error);
    return NextResponse.json({ error: "データ取得に失敗しました" }, { status: 500 });
  }
}

export async function PATCH(req: NextRequest) {
  if (!isAuthenticatedRequest(req)) {
    return NextResponse.json({ error: "認証が必要です" }, { status: 401 });
  }

  try {
    const body = (await req.json()) as {
      id?: string;
      status?: KodomoStatus;
      humanApprovedBy?: string;
      humanApprovedAt?: string;
    };
    if (!body.id || !body.status) {
      return NextResponse.json({ error: "id と status が必要です" }, { status: 400 });
    }

    const posts = await readPosts();
    const index = posts.findIndex((post) => post.id === body.id);
    if (index === -1) {
      return NextResponse.json({ error: "Not found" }, { status: 404 });
    }

    const updated: KodomoPost = {
      ...posts[index],
      status: body.status,
      ...(body.humanApprovedBy !== undefined ? { humanApprovedBy: body.humanApprovedBy } : {}),
      ...(body.humanApprovedAt !== undefined ? { humanApprovedAt: body.humanApprovedAt } : {}),
    };

    posts[index] = updated;
    await fs.writeFile(KODOMO_POSTS_PATH, `${posts.map((post) => JSON.stringify(post)).join("\n")}\n`, "utf8");

    return NextResponse.json(updated);
  } catch (error) {
    console.error("Kodomo posts PATCH error:", error);
    return NextResponse.json({ error: "更新に失敗しました" }, { status: 500 });
  }
}
