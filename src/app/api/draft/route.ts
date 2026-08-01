import { draftMode } from "next/headers";
import { redirect } from "next/navigation";
import { NextRequest, NextResponse } from "next/server";
import { isAuthenticated } from "@/lib/auth";

/**
 * 下書きプレビューの入口。
 *
 * 記事ページは ISR（6時間）でキャッシュされるため、下書きを見るには
 * キャッシュをバイパスする必要がある。Draft Mode は `__prerender_bypass`
 * Cookie を持つリクエストだけをバイパスさせる仕組みで、通常訪問者への
 * 配信は静的キャッシュのまま維持される。
 *
 * 使い方（管理画面にログイン済みの状態で）:
 *   有効化: /api/draft?slug=<記事slug>   → その記事へリダイレクト
 *   解除:   /api/draft?disable=1
 *
 * 旧 `?preview=1` はページを動的レンダリングに落とし ISR を無効化していたため廃止。
 */
export async function GET(request: NextRequest) {
  const draft = await draftMode();
  const { searchParams } = new URL(request.url);

  if (searchParams.get("disable") === "1") {
    draft.disable();
    return NextResponse.json({ draftMode: "disabled" });
  }

  // 管理画面と同じセッションCookieで認証する（プレビュー専用の秘密鍵は増やさない）
  if (!(await isAuthenticated())) {
    return NextResponse.json(
      { error: "認証が必要です。先に /admin にログインしてください。" },
      { status: 401 }
    );
  }

  const slug = searchParams.get("slug");
  if (!slug || !/^[a-z0-9-]+$/.test(slug)) {
    return NextResponse.json(
      { error: "slug パラメータが必要です（例: /api/draft?slug=my-article）" },
      { status: 400 }
    );
  }

  draft.enable();
  redirect(`/articles/${slug}`);
}
