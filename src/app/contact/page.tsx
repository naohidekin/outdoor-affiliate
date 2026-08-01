import type { Metadata } from "next";
import Link from "next/link";
import { getCategories } from "@/lib/db";
import Header from "@/components/Header";
import Footer from "@/components/Footer";

export const revalidate = 86400; // 1日キャッシュ

export const metadata: Metadata = {
  title: "お問い合わせ",
  description:
    "Camp Gear Lab（camp-gear-lab.com）へのお問い合わせ方法のご案内。記事内容の誤り・掲載情報・その他のご連絡はこちらから。",
  alternates: { canonical: "/contact" },
};

export default async function ContactPage() {
  const categories = await getCategories();

  return (
    <>
      <Header categories={categories} />
      <main className="flex-1">
        <article className="max-w-4xl mx-auto px-4 py-12">
          <nav className="text-sm text-slate-500 mb-6" aria-label="パンくず">
            <Link href="/" className="hover:text-lake-600 transition">
              ホーム
            </Link>
            <span className="mx-2 text-slate-400">/</span>
            <span>お問い合わせ</span>
          </nav>

          <h1 className="text-3xl md:text-4xl font-semibold tracking-tight text-ink-strong leading-tight mb-10">
            お問い合わせ
          </h1>

          <div className="prose max-w-none">
            <p>
              Camp Gear Lab へのお問い合わせは、X（旧Twitter）のダイレクトメッセージにて受け付けています。
              記事内容の誤りのご指摘、掲載情報に関するご連絡、その他のご質問など、お気軽にどうぞ。
            </p>

            <div className="not-prose my-8">
              <a
                href="https://twitter.com/camp_gear_lab"
                target="_blank"
                rel="noopener noreferrer"
                className="inline-flex items-center gap-2 bg-ink-strong hover:bg-ink text-white px-6 py-3 rounded-xl text-sm font-medium transition"
              >
                X（@camp_gear_lab）でDMを送る →
              </a>
            </div>

            <h2>お問い合わせの前に</h2>
            <ul>
              <li>
                商品の価格・在庫・返品などについては、当サイトではお答えできません。
                各販売店（楽天市場・Amazon等）へ直接お問い合わせください。
              </li>
              <li>
                個別の医療相談には応じられません。体調に関するご相談は、かかりつけ医にご相談ください。
              </li>
              <li>
                いただいたお問い合わせにはできる限り返信しますが、内容によっては
                お時間をいただく場合や、返信できない場合があります。
              </li>
            </ul>

            <p className="text-sm text-slate-500">
              個人情報の取り扱いについては
              <Link href="/privacy">プライバシーポリシー</Link>
              をご覧ください。
            </p>
          </div>
        </article>
      </main>
      <Footer categories={categories} />
    </>
  );
}
