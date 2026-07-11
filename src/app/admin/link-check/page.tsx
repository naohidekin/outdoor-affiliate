"use client";

import { useEffect, useState } from "react";

type BrokenItem = { id: string; name: string; url: string };
type Report = {
  exists: boolean;
  checkedAt?: string;
  total?: number;
  checked?: number;
  ok?: number;
  broken?: BrokenItem[];
  errors?: BrokenItem[];
  noUrl?: { id: string; name: string }[];
};

function ItemRow({ item, showUrl }: { item: { id: string; name: string; url?: string }; showUrl: boolean }) {
  return (
    <div className="p-3 border-b border-gray-100 last:border-b-0 flex items-center justify-between gap-3">
      <div className="min-w-0">
        <p className="text-sm text-gray-900">{item.name}</p>
        <p className="text-xs text-gray-400 truncate">{item.id}</p>
      </div>
      <div className="flex items-center gap-2 shrink-0">
        {showUrl && item.url && (
          <a
            href={item.url}
            target="_blank"
            rel="noopener noreferrer"
            className="text-xs px-2.5 py-1.5 rounded-lg border border-gray-300 text-gray-600 hover:bg-gray-50"
          >
            リンクを開く
          </a>
        )}
        <a
          href="/admin/products"
          className="text-xs px-2.5 py-1.5 rounded-lg bg-gray-900 text-white hover:bg-gray-700"
        >
          商品管理で修正
        </a>
      </div>
    </div>
  );
}

export default function LinkCheckPage() {
  const [report, setReport] = useState<Report | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    fetch("/api/link-check-report")
      .then(async (r) => {
        if (!r.ok) throw new Error(`API error (${r.status})`);
        return r.json();
      })
      .then(setReport)
      .catch((e) => setError(e.message));
  }, []);

  const broken = report?.broken || [];
  const errors = report?.errors || [];
  const noUrl = report?.noUrl || [];

  return (
    <div className="max-w-4xl mx-auto p-6">
      <h1 className="text-2xl font-bold text-gray-900">🔗 リンク切れ点検</h1>
      <p className="text-sm text-gray-500 mt-1">
        link-check（毎週日曜 6:30）が全商品のAmazonリンクを実査した結果。
        壊れたリンクはクリックされても1円にもならないので、見つけたら商品管理でURLを差し替えてください。
      </p>
      <p className="text-xs mt-3 px-3 py-2 rounded-lg bg-sky-50 text-sky-800 border border-sky-200">
        ℹ️ 本番ではデプロイ時点のスナップショットを表示します（日曜のチェック結果は、次のデータcommit→デプロイで反映）。
        ローカルdevでは常に最新のレポートが見えます。
      </p>

      {error && <p className="mt-4 text-sm text-red-600">エラー: {error}</p>}
      {!report && !error && <p className="mt-6 text-gray-500">読み込み中…</p>}

      {report && !report.exists && (
        <p className="mt-6 text-gray-500">
          レポートがまだありません。日曜朝の自動実行を待つか、Macで <code>npm run check:links</code> を実行してください。
        </p>
      )}

      {report?.exists && (
        <>
          <div className="mt-6 grid grid-cols-2 sm:grid-cols-4 gap-3">
            <div className="bg-white rounded-lg border border-gray-200 p-4">
              <p className="text-xs text-gray-500">最終チェック</p>
              <p className="text-sm font-semibold text-gray-900 mt-1">
                {report.checkedAt ? new Date(report.checkedAt).toLocaleString("ja-JP") : "—"}
              </p>
            </div>
            <div className="bg-white rounded-lg border border-gray-200 p-4">
              <p className="text-xs text-gray-500">正常</p>
              <p className="text-2xl font-bold text-emerald-600">{report.ok ?? 0}</p>
            </div>
            <div className="bg-white rounded-lg border border-gray-200 p-4">
              <p className="text-xs text-gray-500">リンク切れ</p>
              <p className="text-2xl font-bold text-red-600">{broken.length}</p>
            </div>
            <div className="bg-white rounded-lg border border-gray-200 p-4">
              <p className="text-xs text-gray-500">URL未設定</p>
              <p className="text-2xl font-bold text-amber-600">{noUrl.length}</p>
            </div>
          </div>

          <h2 className="mt-8 text-lg font-bold text-gray-900">🔴 リンク切れ（{broken.length}件）</h2>
          <div className="mt-2 bg-white rounded-xl border border-gray-200 overflow-hidden">
            {broken.length === 0 ? (
              <p className="p-4 text-sm text-gray-500">リンク切れはありません 🎉</p>
            ) : (
              broken.map((b) => <ItemRow key={b.id} item={b} showUrl />)
            )}
          </div>

          {errors.length > 0 && (
            <>
              <h2 className="mt-8 text-lg font-bold text-gray-900">⚠️ チェックエラー（{errors.length}件）</h2>
              <p className="text-xs text-gray-500 mt-1">
                タイムアウト等で確認できなかったもの。CAPTCHAの可能性もあるので「リンクを開く」で目視確認を。
              </p>
              <div className="mt-2 bg-white rounded-xl border border-gray-200 overflow-hidden">
                {errors.map((b) => <ItemRow key={b.id} item={b} showUrl />)}
              </div>
            </>
          )}

          {noUrl.length > 0 && (
            <>
              <h2 className="mt-8 text-lg font-bold text-gray-900">◻️ AmazonURL未設定（{noUrl.length}件）</h2>
              <div className="mt-2 bg-white rounded-xl border border-gray-200 overflow-hidden">
                {noUrl.map((b) => <ItemRow key={b.id} item={b} showUrl={false} />)}
              </div>
            </>
          )}
        </>
      )}
    </div>
  );
}
