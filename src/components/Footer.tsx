import Link from "next/link";
import { Mountain, ExternalLink } from "lucide-react";
import { Category } from "@/lib/types";

export default function Footer({ categories = [] }: { categories?: Category[] }) {
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
              現役小児科医・2児の父が、子ども連れキャンプの安全性と実用性を重視してギアを比較します。
            </p>
          </div>
          <div>
            <h4 className="text-slate-500 font-medium mb-3 text-xs uppercase tracking-wider">
              カテゴリ
            </h4>
            <ul className="space-y-2 text-sm columns-2">
              {categories.length > 0
                ? categories.map((c) => (
                    <li key={c.id}>
                      <Link
                        href={`/category/${c.slug}`}
                        className="text-slate-600 hover:text-lake-600 transition"
                      >
                        {c.name}
                      </Link>
                    </li>
                  ))
                : ["tent", "sleeping-bag", "burner", "light", "firepit", "tarp"].map(
                    (slug) => (
                      <li key={slug}>
                        <Link
                          href={`/category/${slug}`}
                          className="text-slate-600 hover:text-lake-600 transition"
                        >
                          {slug}
                        </Link>
                      </li>
                    )
                  )}
            </ul>
          </div>
          <div>
            <h4 className="text-slate-500 font-medium mb-3 text-xs uppercase tracking-wider">
              このサイトについて
            </h4>
            <p className="text-sm leading-relaxed text-slate-600">
              当サイトはアフィリエイト広告（プロモーション）を利用しています。
              商品リンクから購入いただくと運営費の一部になります。
            </p>
            <ul className="mt-3 space-y-2 text-sm">
              <li>
                <Link
                  href="/about"
                  className="text-lake-600 hover:text-lake-700 transition font-medium"
                >
                  運営者情報・編集ポリシー →
                </Link>
              </li>
              <li>
                <Link
                  href="/privacy"
                  className="text-lake-600 hover:text-lake-700 transition font-medium"
                >
                  プライバシーポリシー →
                </Link>
              </li>
              <li>
                <Link
                  href="/contact"
                  className="text-lake-600 hover:text-lake-700 transition font-medium"
                >
                  お問い合わせ →
                </Link>
              </li>
            </ul>
            <a
              href="https://room.rakuten.co.jp/room_naomaru/items"
              target="_blank"
              rel="noopener noreferrer nofollow sponsored"
              className="inline-flex items-center gap-1.5 mt-4 px-3 py-1.5 rounded-full bg-rose-50 text-rose-700 text-xs font-medium hover:bg-rose-100 transition"
            >
              <ExternalLink className="w-3 h-3" />
              楽天ROOM
            </a>
          </div>
        </div>
        <div className="border-t border-line-soft mt-10 pt-6 text-center text-xs text-slate-400 space-y-2">
          <p>
            Amazonのアソシエイトとして、Outdoor Gear Lab
            は適格販売により収入を得ています。
          </p>
          <p>&copy; {new Date().getFullYear()} Outdoor Gear Lab. All rights reserved.</p>
        </div>
      </div>
    </footer>
  );
}
