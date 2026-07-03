import Link from "next/link";

// 景品表示法（ステマ規制・2023年10月施行）対応:
// アフィリエイト広告を含むページには広告である旨を明示する（記事末尾に表示）
export default function AffiliateDisclosure() {
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
