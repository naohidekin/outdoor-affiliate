import { NextRequest, NextResponse } from "next/server";
import { isAuthenticated } from "@/lib/auth";
import {
  revalidateArticlePages,
  revalidateAllArticlePages,
} from "@/lib/revalidate";

// 外部プロセス（Mac側の価格同期 price-monitor / sync-to-supabase 等）が
// Supabaseを直接更新した後にISRキャッシュを無効化するためのエンドポイント。
// 認証は管理画面セッション or REVALIDATE_SECRET ヘッダのどちらか。
// 秘密鍵が未設定の環境では外部からは叩けない（管理画面ログインのみ）
function hasValidSecret(request: NextRequest): boolean {
  const secret = process.env.REVALIDATE_SECRET || "";
  if (!secret) return false;
  return request.headers.get("x-revalidate-secret") === secret;
}

export async function POST(request: NextRequest) {
  if (!hasValidSecret(request) && !(await isAuthenticated())) {
    return NextResponse.json({ error: "認証が必要です" }, { status: 401 });
  }

  const body = await request.json().catch(() => ({}));

  // { slug, categoryId } 指定で単一記事、{ all: true } で全記事を無効化
  if (body.all) {
    revalidateAllArticlePages();
    return NextResponse.json({ revalidated: "all" });
  }
  if (typeof body.slug === "string" && body.slug) {
    await revalidateArticlePages(body.slug, body.categoryId);
    return NextResponse.json({ revalidated: body.slug });
  }
  return NextResponse.json(
    { error: "slug または all を指定してください" },
    { status: 400 }
  );
}
