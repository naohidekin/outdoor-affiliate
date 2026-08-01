import Link from "next/link";

// 景品表示法（ステマ規制・2023年10月施行）対応:
// アフィリエイト広告を含むページには広告である旨を明示する。
// variant="inline" は最初の購入導線より前に置く簡易表示（広告に接する前に
// 認識できる位置に出すのが規制上の安全側）。既定の詳細版は記事末尾に表示する。
export default function AffiliateDisclosure({
  variant = "full",
}: {
  variant?: "full" | "inline";
}) {
  if (variant === "inline") {
    return (
      <p className="text-xs text-slate-500 mt-4 mb-1">
        <span className="font-medium text-slate-600 border border-line-soft rounded px-1.5 py-0.5">
          PR
        </span>
        <span className="ml-2">
          本記事にはアフィリエイト広告が含まれます
        </span>
      </p>
    );
  }

  return (
    <p className="text-xs text-slate-500 bg-slate-50 border border-line-soft rounded-lg px-4 py-2.5 mt-10">
      <span className="font-medium text-slate-600">PR</span>
      <span className="mx-2 text-slate-300">|</span>
      本記事にはアフィリエイト広告（プロモーション）が含まれます。詳しくは
      <Link href="/about" className="underline hover:text-lake-600 transition">
        編集ポリシー
      </Link>
      をご覧ください。
    </p>
  );
}
