import { NextRequest, NextResponse } from "next/server";
import { isAuthenticated } from "@/lib/auth";
import {
  getSheetsXPosts,
  getSheetsXPostById,
  saveSheetsXPost,
  deleteSheetsXPost,
} from "@/lib/sheets-xposts";
import { XPost } from "@/lib/types";

export async function GET() {
  if (!(await isAuthenticated())) {
    return NextResponse.json({ error: "認証が必要です" }, { status: 401 });
  }
  const posts = await getSheetsXPosts();
  return NextResponse.json(posts);
}

export async function PATCH(req: NextRequest) {
  if (!(await isAuthenticated())) {
    return NextResponse.json({ error: "認証が必要です" }, { status: 401 });
  }
  const body = await req.json();
  const result = await getSheetsXPostById(body.id);
  if (!result) {
    return NextResponse.json({ error: "Not found" }, { status: 404 });
  }

  const updated: XPost = { ...result.post, ...body };
  await saveSheetsXPost(updated);
  return NextResponse.json(updated);
}

export async function DELETE(req: NextRequest) {
  if (!(await isAuthenticated())) {
    return NextResponse.json({ error: "認証が必要です" }, { status: 401 });
  }
  const { searchParams } = new URL(req.url);
  const id = searchParams.get("id");
  if (!id) {
    return NextResponse.json({ error: "id required" }, { status: 400 });
  }
  await deleteSheetsXPost(id);
  return NextResponse.json({ ok: true });
}
