import Link from "next/link";
import { Mountain } from "lucide-react";

export default function Footer() {
  return (
    <footer className="bg-[#2a2320] text-gray-400 mt-auto">
      <div className="max-w-6xl mx-auto px-4 py-12">
        <div className="grid md:grid-cols-3 gap-8">
          <div>
            <h3 className="text-white font-bold text-lg mb-3 flex items-center gap-2" style={{ fontFamily: 'var(--font-heading)' }}>
              <Mountain className="w-5 h-5 text-[#7a9a6d]" />
              Outdoor Gear Lab
            </h3>
            <p className="text-sm leading-relaxed text-gray-500">
              「どれ買えばいい？」に答えるアウトドアギア比較サイト。
              実際に使って分かったリアルな情報をお届けします。
            </p>
          </div>
          <div>
            <h4 className="text-gray-300 font-semibold mb-3 text-sm uppercase tracking-wider">カテゴリ</h4>
            <ul className="space-y-2 text-sm">
              <li>
                <Link href="/category/tent" className="hover:text-[#7a9a6d] transition">
                  テント
                </Link>
              </li>
              <li>
                <Link href="/category/sleeping-bag" className="hover:text-[#7a9a6d] transition">
                  シュラフ・寝袋
                </Link>
              </li>
              <li>
                <Link href="/category/burner" className="hover:text-[#7a9a6d] transition">
                  バーナー・コンロ
                </Link>
              </li>
              <li>
                <Link href="/category/lantern" className="hover:text-[#7a9a6d] transition">
                  ランタン
                </Link>
              </li>
            </ul>
          </div>
          <div>
            <h4 className="text-gray-300 font-semibold mb-3 text-sm uppercase tracking-wider">このサイトについて</h4>
            <p className="text-sm leading-relaxed text-gray-500">
              当サイトはアフィリエイトプログラムに参加しています。
              商品リンクから購入いただくと運営費の一部になります。
            </p>
          </div>
        </div>
        <div className="border-t border-gray-700/50 mt-8 pt-8 text-center text-xs text-gray-600">
          &copy; {new Date().getFullYear()} Outdoor Gear Lab. All rights reserved.
        </div>
      </div>
    </footer>
  );
}
