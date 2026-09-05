import type { Metadata } from "next";
import Link from "next/link";
import { getCategories } from "@/lib/db";
import Header from "@/components/Header";
import Footer from "@/components/Footer";

export const revalidate = 86400; // 1日キャッシュ

export const metadata: Metadata = {
  title: "プライバシーポリシー",
  description:
    "Camp Gear Lab（camp-gear-lab.com）のプライバシーポリシー。アクセス解析・広告配信・Cookieの取り扱いについて説明します。",
  alternates: { canonical: "/privacy" },
};

export default async function PrivacyPage() {
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
            <span>プライバシーポリシー</span>
          </nav>

          <h1 className="text-3xl md:text-4xl font-semibold tracking-tight text-ink-strong leading-tight mb-10">
            プライバシーポリシー
          </h1>

          <div className="prose max-w-none">
            <p>
              Camp Gear Lab（https://camp-gear-lab.com、以下「当サイト」）は、
              訪問者のプライバシーを尊重し、個人情報の保護に努めます。
              本ポリシーでは、当サイトにおける情報の取り扱いを説明します。
            </p>

            <h2>広告の配信について</h2>
            <p>
              当サイトは、以下のアフィリエイトプログラムに参加しています。
              記事内の商品リンクを経由して商品・サービスを購入された場合、
              提携先から当サイトに紹介料が支払われることがあります。
              リンクを経由しても、購入価格が変わることはありません。
            </p>
            <ul>
              <li>楽天アフィリエイト（楽天グループ株式会社）</li>
              <li>Amazonアソシエイト・プログラム（Amazon.co.jp）</li>
            </ul>
            <p>
              当サイトは、Amazon.co.jpを宣伝しリンクすることによってサイトが紹介料を獲得できる手段を提供することを目的に設定されたアフィリエイトプログラムである、Amazonアソシエイト・プログラムの参加者です。
            </p>
            <p>
              アフィリエイト広告を含む記事には、記事上部に「PR」の表記を掲載しています。
            </p>

            <h2>アクセス解析ツールについて</h2>
            <p>
              当サイトは、Googleによるアクセス解析ツール「Googleアナリティクス（GA4）」を利用しています。
              Googleアナリティクスはトラフィックデータの収集のためにCookieを使用します。
              このデータは匿名で収集されており、個人を特定するものではありません。
            </p>
            <p>
              Cookieの利用は、ブラウザの設定から無効にすることができます。
              データの収集・処理の仕組みについては、
              <a
                href="https://policies.google.com/technologies/partner-sites?hl=ja"
                target="_blank"
                rel="noopener noreferrer"
              >
                Googleのポリシーと規約
              </a>
              をご確認ください。
            </p>

            <h2>商品リンクのクリック計測について</h2>
            <p>
              Google Analyticsでは、商品リンクの画面内への表示、クリック、
              選び方ガイドからの記事への移動も計測します。商品・販売店・ページ内の位置ごとに、
              案内の見つけやすさを改善するために利用します。販売店での購入を直接計測するものではありません。
            </p>
            <p>
              当サイトでは、記事の改善とアフィリエイト成果の分析のため、
              商品リンク（Amazon・楽天市場・Yahoo!ショッピング等）がクリックされた際に、
              以下の情報を当サイトのサーバーに記録しています。
            </p>
            <ul>
              <li>クリックされた商品・販売店・ページ内の位置</li>
              <li>クリックが発生したページのURLと日時</li>
              <li>ブラウザの種類（User-Agent）</li>
              <li>IPアドレスを復元できない形に変換した識別子（同日内の重複クリック判定のみに使用）</li>
            </ul>
            <p>
              IPアドレスそのものは保存していません。これらの記録は個人の特定を目的とせず、
              「どの記事のどの位置のリンクが役立っているか」の分析にのみ利用し、
              収集から1年を目安に削除します。第三者に提供することはありません。
            </p>

            <h2>個人情報の利用目的</h2>
            <p>
              当サイトへのお問い合わせの際にいただく情報（お名前・ご連絡先等）は、
              お問い合わせへの回答にのみ利用し、それ以外の目的では利用しません。
              法令に基づく場合を除き、本人の同意なく第三者に開示することはありません。
            </p>

            <h2>免責事項</h2>
            <p>
              当サイトに掲載する商品情報・価格は記事執筆時点のものです。
              最新の価格・仕様・在庫状況は、必ずリンク先の販売ページでご確認ください。
              当サイトの情報を利用したことによって生じたいかなる損害についても、
              当サイトは責任を負いかねます。
            </p>
            <p>
              当サイトの記事には運営者（医師）の経験に基づく安全に関する情報が含まれますが、
              個別の医療相談・診断に代わるものではありません。
              体調に関する具体的なご相談は、かかりつけ医にご相談ください。
            </p>

            <h2>著作権について</h2>
            <p>
              当サイトに掲載されている文章・画像等の著作物の無断転載を禁止します。
              引用される場合は、出典（当サイト名とURL）を明記してください。
            </p>

            <h2>プライバシーポリシーの変更</h2>
            <p>
              本ポリシーの内容は、法令の変更やサイト運営方針の変更に応じて、
              予告なく改定することがあります。変更後のポリシーは本ページに掲載した時点で効力を生じます。
            </p>

            <p className="text-sm text-slate-500">
              制定日: 2026年7月3日
              <br />
              運営者:{" "}
              <Link href="/about">Camp Gear Lab（運営者情報はこちら）</Link>
            </p>
          </div>
        </article>
      </main>
      <Footer categories={categories} />
    </>
  );
}
