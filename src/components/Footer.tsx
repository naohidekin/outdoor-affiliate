import Link from "next/link";
import { Mountain } from "lucide-react";

export default function Footer() {
  return (
    <footer className="bg-white border-t border-line mt-auto">
      <div className="max-w-6xl mx-auto px-4 py-14">
        <div className="grid md:grid-cols-3 gap-10">
          <div>
            <h3 className="text-ink-strong font-semibold text-base mb-3 flex items-center gap-2">
              <Mountain className="w-5 h-5 text-lake-600" strokeWidth={2} />
              Outdoor Gear Lab
            </h3>
            <p className="text-sm leading-relaxed text-slate-600">
              「どれ買えばいい？」に答えるアウトドアギア比較サイト。
              長野のキャンプ歴 10 年・ギア男が、実際に使って分かったリアルな情報を発信しています。
            </p>
          </div>
          <div>
            <h4 className="text-slate-500 font-medium mb-3 text-xs uppercase tracking-wider">
              カテゴリ
            </h4>
            <ul className="space-y-2 text-sm">
              <li>
                <Link
                  href="/category/tent"
                  className="text-slate-600 hover:text-lake-600 transition"
                >
                  テント
                </Link>
              </li>
              <li>
                <Link
                  href="/category/sleeping-bag"
                  className="text-slate-600 hover:text-lake-600 transition"
                >
                  シュラフ・寝袋
                </Link>
              </li>
              <li>
                <Link
                  href="/category/burner"
                  className="text-slate-600 hover:text-lake-600 transition"
                >
                  バーナー・コンロ
                </Link>
              </li>
              <li>
                <Link
                  href="/category/lantern"
                  className="text-slate-600 hover:text-lake-600 transition"
                >
                  ランタン
                </Link>
              </li>
            </ul>
          </div>
          <div>
            <h4 className="text-slate-500 font-medium mb-3 text-xs uppercase tracking-wider">
              このサイトについて
            </h4>
            <p className="text-sm leading-relaxed text-slate-600">
              当サイトはアフィリエイトプログラムに参加しています。
              商品リンクから購入いただくと運営費の一部になります。
            </p>
          </div>
        </div>
        <div className="border-t border-line-soft mt-10 pt-6 text-center text-xs text-slate-400">
          &copy; {new Date().getFullYear()} Outdoor Gear Lab. All rights reserved.
        </div>
      </div>
    </footer>
  );
}
