import fs from "node:fs/promises";
import path from "node:path";
import { NextRequest, NextResponse } from "next/server";
import { isAuthenticated } from "@/lib/auth";

export const runtime = "nodejs";

const HOME = process.env.HOME || "";
const AMBLE_POSTS_PATH = path.join(HOME, "Desktop/AI関連/claude/san-pedinvestor-x/data/x/posts.jsonl");

type AmbleStatus = "draft" | "cross_reviewed" | "evidence_ok" | "reviewed" | "approved" | "posted" | "rejected" | "dead_letter";

type ABCDScores = {
  a?: number | null;
  b?: number | null;
  c?: number | null;
  d?: number | null;
  ai?: number | null;
};

type AmblePost = {
  id: string;
  body: string;
  type: string;
  status: AmbleStatus;
  wiseScores?: ABCDScores | null;
  gptScores?: ABCDScores | null;
  claimRisk?: string | null;
  _voiceSource?: string;
  _format?: string;
  [key: string]: unknown;
};

function parseJsonl(content: string): AmblePost[] {
  return content
    .trim()
    .split("\n")
    .filter(Boolean)
    .map((line) => JSON.parse(line) as AmblePost);
}

function toJsonl(posts: AmblePost[]): string {
  return posts.map((p) => JSON.stringify(p)).join("\n") + "\n";
}

async function readPosts(): Promise<AmblePost[]> {
  const raw = await fs.readFile(AMBLE_POSTS_PATH, "utf8");
  return parseJsonl(raw);
}

export async function GET() {
  if (!(await isAuthenticated())) {
    return NextResponse.json({ error: "認証が必要です" }, { status: 401 });
  }

  try {
    const posts = await readPosts();
    // フロントエンド互換: text フィールドも返す
    const mapped = posts.map((p) => ({
      ...p,
      text: p.body,
      score_a: p.wiseScores?.a ?? null,
      score_b: p.wiseScores?.b ?? null,
      score_c: p.wiseScores?.c ?? null,
      score_d: p.wiseScores?.d ?? null,
      score_ai: p.wiseScores?.ai ?? null,
    }));
    return NextResponse.json(mapped);
  } catch (error) {
    console.error("Amble posts GET error:", error);
    return NextResponse.json({ error: "データ取得に失敗しました" }, { status: 500 });
  }
}

export async function PATCH(req: NextRequest) {
  if (!(await isAuthenticated())) {
    return NextResponse.json({ error: "認証が必要です" }, { status: 401 });
  }

  try {
    const reqBody = (await req.json()) as { id?: string; status?: AmbleStatus };
    if (!reqBody.id || !reqBody.status) {
      return NextResponse.json({ error: "id と status が必要です" }, { status: 400 });
    }

    const posts = await readPosts();
    const index = posts.findIndex((post) => post.id === reqBody.id);
    if (index === -1) {
      return NextResponse.json({ error: "Not found" }, { status: 404 });
    }

    posts[index] = { ...posts[index], status: reqBody.status };
    await fs.writeFile(AMBLE_POSTS_PATH, toJsonl(posts), "utf8");

    return NextResponse.json({ ...posts[index], text: posts[index].body });
  } catch (error) {
    console.error("Amble posts PATCH error:", error);
    return NextResponse.json({ error: "更新に失敗しました" }, { status: 500 });
  }
}

export async function DELETE(req: NextRequest) {
  if (!(await isAuthenticated())) {
    return NextResponse.json({ error: "認証が必要です" }, { status: 401 });
  }

  try {
    const reqBody = (await req.json()) as { id?: string };
    if (!reqBody.id) {
      return NextResponse.json({ error: "id が必要です" }, { status: 400 });
    }

    const posts = await readPosts();
    const index = posts.findIndex((post) => post.id === reqBody.id);
    if (index === -1) {
      return NextResponse.json({ error: "Not found" }, { status: 404 });
    }

    const deleted = posts[index];
    posts.splice(index, 1);
    await fs.writeFile(AMBLE_POSTS_PATH, toJsonl(posts), "utf8");

    return NextResponse.json({ success: true, deleted });
  } catch (error) {
    console.error("Amble posts DELETE error:", error);
    return NextResponse.json({ error: "削除に失敗しました" }, { status: 500 });
  }
}
