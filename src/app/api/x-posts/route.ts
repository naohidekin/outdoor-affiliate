import { NextRequest, NextResponse } from "next/server";
import { getXPosts, getXPostById, saveXPost, deleteXPost } from "@/lib/db";
import { XPost } from "@/lib/types";

export async function GET() {
  const posts = getXPosts();
  return NextResponse.json(posts);
}

export async function POST(req: NextRequest) {
  const body = await req.json();
  const now = new Date().toISOString();
  const posts = getXPosts();
  const nextId = `xpost-${String(posts.length + 1).padStart(3, "0")}`;

  const post: XPost = {
    id: body.id || nextId,
    text: body.text,
    type: body.type || "comparison",
    articleSlug: body.articleSlug || undefined,
    status: body.status || "draft",
    scheduledDay: body.scheduledDay || undefined,
    scheduledTime: body.scheduledTime || undefined,
    createdAt: now,
  };

  saveXPost(post);
  return NextResponse.json(post, { status: 201 });
}

export async function PATCH(req: NextRequest) {
  const body = await req.json();
  const existing = getXPostById(body.id);
  if (!existing) {
    return NextResponse.json({ error: "Not found" }, { status: 404 });
  }

  const updated: XPost = { ...existing, ...body };
  saveXPost(updated);
  return NextResponse.json(updated);
}

export async function DELETE(req: NextRequest) {
  const { searchParams } = new URL(req.url);
  const id = searchParams.get("id");
  if (!id) {
    return NextResponse.json({ error: "id required" }, { status: 400 });
  }
  deleteXPost(id);
  return NextResponse.json({ ok: true });
}
