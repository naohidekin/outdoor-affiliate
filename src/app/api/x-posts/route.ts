import { NextRequest, NextResponse } from "next/server";
import { isAuthenticated } from "@/lib/auth";
import {
  getSheetsXPosts,
  getSheetsXPostById,
  saveSheetsXPost,
  deleteSheetsXPost,
} from "@/lib/sheets-xposts";

export async function GET() {
  try {
    const posts = await getSheetsXPosts();
    return NextResponse.json(posts);
  } catch (err) {
    console.error("Sheets読み取りエラー:", err);
    return NextResponse.json(
      { error: "データの取得に失敗しました" },
      { status: 500 }
    );
  }
}

export async function PATCH(request: NextRequest) {
  if (!(await isAuthenticated())) {
    return NextResponse.json({ error: "認証が必要です" }, { status: 401 });
  }

  try {
    const body = await request.json();
    const result = await getSheetsXPostById(body.id);
    if (!result) {
      return NextResponse.json(
        { error: "ポストが見つかりません" },
        { status: 404 }
      );
    }

    const updated = {
      ...result.post,
      ...(body.text !== undefined && { text: body.text }),
      ...(body.status !== undefined && { status: body.status }),
      ...(body.scheduledDate !== undefined && {
        scheduledDate: body.scheduledDate,
      }),
      ...(body.status === "posted" && { postedAt: new Date().toISOString() }),
    };

    await saveSheetsXPost(updated);
    return NextResponse.json(updated);
  } catch (err) {
    console.error("Sheets更新エラー:", err);
    return NextResponse.json(
      { error: "更新に失敗しました" },
      { status: 500 }
    );
  }
}

export async function DELETE(request: NextRequest) {
  if (!(await isAuthenticated())) {
    return NextResponse.json({ error: "認証が必要です" }, { status: 401 });
  }

  const { searchParams } = new URL(request.url);
  const id = searchParams.get("id");
  if (!id) {
    return NextResponse.json({ error: "IDが必要です" }, { status: 400 });
  }

  try {
    await deleteSheetsXPost(id);
    return NextResponse.json({ success: true });
  } catch (err) {
    console.error("Sheets削除エラー:", err);
    return NextResponse.json(
      { error: "削除に失敗しました" },
      { status: 500 }
    );
  }
}
