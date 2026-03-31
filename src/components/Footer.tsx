import Link from "next/link";

export default function Footer() {
  return (
    <footer className="bg-gray-900 text-gray-400 mt-auto">
      <div className="max-w-6xl mx-auto px-4 py-12">
        <div className="grid md:grid-cols-3 gap-8">
          <div>
            <h3 className="text-white font-bold text-lg mb-3">
              Outdoor Gear Lab
            </h3>
            <p className="text-sm">
              アウトドア用品の比較・レビューサイト。
              実際に使って分かったリアルな情報をお届けします。
            </p>
          </div>
          <div>
            <h4 className="text-white font-semibold mb-3">カテゴリ</h4>
            <ul className="space-y-2 text-sm">
              <li>
                <Link href="/category/tent" className="hover:text-white transition">
                  テント
                </Link>
              </li>
              <li>
                <Link href="/category/sleeping-bag" className="hover:text-white transition">
                  シュラフ・寝袋
                </Link>
              </li>
              <li>
                <Link href="/category/burner" className="hover:text-white transition">
                  バーナー・コンロ
                </Link>
              </li>
            </ul>
          </div>
          <div>
            <h4 className="text-white font-semibold mb-3">このサイトについて</h4>
            <p className="text-sm">
              当サイトはアフィリエイトプログラムに参加しています。
              商品リンクから購入いただくと運営費の一部になります。
            </p>
          </div>
        </div>
        <div className="border-t border-gray-800 mt-8 pt-8 text-center text-sm">
          &copy; {new Date().getFullYear()} Outdoor Gear Lab. All rights reserved.
        </div>
      </div>
    </footer>
  );
}
