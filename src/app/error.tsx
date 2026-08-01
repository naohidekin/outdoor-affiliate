"use client";

import Link from "next/link";
import { useEffect } from "react";

// データ取得（Supabase）が一時的に失敗したときの受け皿。
// これが無いと Next.js の既定500画面が出てサイト全体が壊れて見える。
export default function Error({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  useEffect(() => {
    console.error("[error boundary]", error);
  }, [error]);

  return (
    <main className="min-h-screen flex items-center justify-center px-4 bg-snow">
      <div className="max-w-md text-center">
        <p className="text-sm font-medium text-lake-600 mb-2">Camp Gear Lab</p>
        <h1 className="text-2xl font-semibold text-ink-strong tracking-tight mb-3">
          ページを読み込めませんでした
        </h1>
        <p className="text-sm text-slate-600 leading-relaxed mb-6">
          一時的な不具合が発生しています。少し時間をおいて再度お試しください。
        </p>
        <div className="flex gap-3 justify-center">
          <button
            onClick={reset}
            className="px-5 py-2 rounded-lg text-sm font-medium text-white bg-lake-600 hover:bg-lake-700 transition"
          >
            再読み込み
          </button>
          <Link
            href="/"
            className="px-5 py-2 rounded-lg text-sm font-medium text-lake-700 bg-white border border-line hover:bg-lake-50 transition"
          >
            トップへ戻る
          </Link>
        </div>
      </div>
    </main>
  );
}
