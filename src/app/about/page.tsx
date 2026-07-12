import type { Metadata } from "next";
import Link from "next/link";
import { getCategories } from "@/lib/db";
import Header from "@/components/Header";
import Footer from "@/components/Footer";

export const revalidate = 86400; // 1日キャッシュ

export const metadata: Metadata = {
  title: "このサイトについて | Camp Gear Lab",
  description:
    "現役小児科医・キャンプ歴10年が運営するアウトドアギア比較サイト「Camp Gear Lab」の運営者プロフィールと編集ポリシーをご紹介します。",
  alternates: { canonical: "/about" },
  openGraph: {
    title: "このサイトについて | Camp Gear Lab",
    description:
      "現役小児科医・キャンプ歴10年が運営するアウトドアギア比較サイト「Camp Gear Lab」の運営者プロフィールと編集ポリシーをご紹介します。",
    url: "/about",
    type: "website",
    siteName: "Camp Gear Lab",
    locale: "ja_JP",
  },
};

const personJsonLd = {
  "@context": "https://schema.org",
  "@type": "Person",
  name: "ギア男",
  alternateName: "Camp Gear Lab 編集長",
  jobTitle: "小児科医（開業医）",
  description:
    "現役の小児科開業医「ギア男」。キャンプ歴10年、2児の父。医師目線で家族が安全に楽しめるアウトドアギアを比較・検証。",
  url: "https://camp-gear-lab.com/about",
  worksFor: {
    "@type": "Organization",
    name: "Camp Gear Lab",
    url: "https://camp-gear-lab.com",
  },
  knowsAbout: ["キャンプギア", "ファミリーキャンプ", "アウトドア医学", "小児科"],
  sameAs: [
    "https://x.com/camp_gear_lab",
    "https://twitter.com/camp_gear_lab",
    "https://room.rakuten.co.jp/room_naomaru",
  ],
};

export default async function AboutPage() {
  const categories = await getCategories();

  return (
    <>
      <script
        type="application/ld+json"
        dangerouslySetInnerHTML={{ __html: JSON.stringify(personJsonLd) }}
      />
      <Header categories={categories} />
      <main className="flex-1">
        <article className="max-w-4xl mx-auto px-4 py-12">
          {/* パンくず */}
          <nav className="text-sm text-slate-500 mb-6" aria-label="パンくず">
            <Link href="/" className="hover:text-lake-600 transition">
              ホーム
            </Link>
            <span className="mx-2 text-slate-400">/</span>
            <span>このサイトについて</span>
          </nav>

          <h1 className="text-3xl md:text-4xl font-semibold tracking-tight text-ink-strong leading-tight mb-5">
            このサイトについて
          </h1>

          {/* 医師性バッジ */}
          <div className="flex flex-wrap items-center gap-3 text-sm mb-10 pb-6 border-b border-line">
            <span className="inline-flex items-center gap-1.5 bg-emerald-50 text-emerald-800 px-3 py-1.5 rounded-full font-medium">
              🩺 現役小児科医監修
            </span>
            <span className="inline-flex items-center gap-1.5 bg-lake-50 text-lake-700 px-3 py-1.5 rounded-full font-medium">
              🏕️ キャンプ歴10年
            </span>
            <span className="inline-flex items-center gap-1.5 bg-amber-50 text-amber-800 px-3 py-1.5 rounded-full font-medium">
              👨‍👩‍👧‍👦 2児の父
            </span>
          </div>

          <div className="prose max-w-none">
            <p>
              「Camp Gear Lab」は、<strong>現役の小児科医</strong>
              が運営するアウトドアギアの比較・レビューサイトです。
            </p>
            <p>
              カタログスペックの羅列ではなく、医師としての視点と、キャンプ歴10年で
              積み上げた実体験を組み合わせて、「家族で安全に、長く使える」ギアを
              お伝えすることを目的にしています。
            </p>

            <hr />

            <h2>運営者プロフィール</h2>
            <ul>
              <li>
                <strong>専門</strong>：小児科
              </li>
              <li>
                <strong>診療形態</strong>：開業医（関東圏）
              </li>
              <li>
                <strong>キャンプ歴</strong>：10年以上
              </li>
              <li>
                <strong>家族構成</strong>：配偶者、子2人
              </li>
              <li>
                <strong>趣味</strong>：キャンプ、アウトドアギア収集
              </li>
            </ul>
            <p>
              実名・所属クリニックは、患者様のプライバシー保護および職業倫理上の
              観点から非公開とさせていただいています。匿名運営は私自身の意志に
              よる選択であり、その代わりに
              <strong>
                情報の正確性と実体験ベースの記述に最大限の責任を持つ
              </strong>
              ことをお約束します。
            </p>

            <hr />

            <h2>このサイトの編集ポリシー</h2>

            <h3>0. 記事内の情報区分について</h3>
            <p>
              本サイトの記事には、2種類の情報が混在することがあります。読者が区別して参照できるよう、以下の基準で記述しています。
            </p>
            <ul>
              <li>
                <strong>実体験レビュー</strong>：運営者が実際に購入・使用したギアに基づく評価。個人の体験であり、同条件での効果を保証するものではありません。
              </li>
              <li>
                <strong>医学的・安全情報</strong>：厚生労働省・学会ガイドライン・製品表示などの公的情報をもとに記述。個別の医療判断には使用せず、必ず医療機関に相談してください。
              </li>
            </ul>
            <p>
              「医師から一言」セクションはいずれも一般的な健康情報であり、個別の診断や治療方針の提示ではありません。
            </p>

            <h3>1. 安全性を医学的観点から評価する</h3>
            <p>
              虫除け、熱中症対策、救急用品、暖房器具など「安全性が問われる装備」に
              ついては、医師としての専門知識を踏まえて評価しています。
              特に小児・乳幼児への影響については、慎重に情報を検討しています。
            </p>

            <h3>2. メリットだけでなくデメリットも書く</h3>
            <p>
              アフィリエイト収益を得ているサイトですが、推奨内容は実体験と
              医学的判断に基づきます。「合わない人」「向かない用途」も明記し、
              読者にとって本当に必要な選択を支援することを優先します。
            </p>

            <h3>3. アフィリエイトリンクの開示</h3>
            <p>
              本サイトには Amazon アソシエイト・楽天アフィリエイト等の
              アフィリエイトリンクが含まれます。リンク経由でご購入いただくと、
              サイト運営費の一部となります。ただし、ランキングや評価は
              紹介料の有無に左右されません。
            </p>

            <hr />

            <h2>医療情報の取り扱いについて</h2>
            <p>
              本サイトに含まれる医療関連の記述は、一般的な健康情報の提供を
              目的としています。
            </p>
            <ul>
              <li>個別の症状・疾患に関する診断や治療方針の提示は行いません</li>
              <li>体調に異常がある場合は、必ず医療機関を受診してください</li>
              <li>緊急時は迷わず救急車（119）を呼んでください</li>
              <li>
                お子様の症状で判断に迷う場合は、小児救急電話相談「#8000」をご活用ください
              </li>
            </ul>
            <p>
              医薬品・医療機器に該当する製品については、医薬品医療機器等法（薬機法）
              および関連ガイドラインに準じて記述しています。誇大な効能効果表現は避け、
              製造販売業者の正式な情報に基づいてご紹介します。
            </p>

            <hr />

            <h2>得意とする領域</h2>
            <p>
              医師×キャンパーという視点が特に活きるのは、以下のような
              「安全性に関わる装備・知識」です。
            </p>
            <ul>
              <li>子連れキャンプの救急セット選び</li>
              <li>キャンプでの熱中症・低体温症対策</li>
              <li>虫除け・防虫対策（成分別の安全性比較）</li>
              <li>一酸化炭素中毒の予防（暖房器具の選び方）</li>
              <li>冬キャンプの寒冷対策と防寒着選び</li>
              <li>食中毒予防とクーラーボックス活用</li>
              <li>蛇・ハチ・マダニ対策</li>
            </ul>
            <p>
              これらのテーマでは、メーカーや一般的なキャンプメディアには
              書けない、医学的根拠に基づいた情報をお届けします。
            </p>

            <hr />

            <h2>運営情報</h2>
            <ul>
              <li>
                <strong>サイト名</strong>：Camp Gear Lab
              </li>
              <li>
                <strong>URL</strong>：https://camp-gear-lab.com
              </li>
              <li>
                <strong>運営者</strong>：ギア男（現役小児科開業医・ペンネームで運営）
              </li>
              <li>
                <strong>収益源</strong>：Amazonアソシエイト、楽天アフィリエイト ほか
              </li>
            </ul>

            <hr />

            <h2>ご連絡先</h2>
            <p>
              ご意見・ご質問・記事監修のご依頼などは、お問い合わせフォームから
              お問い合わせください。
            </p>
            <p className="text-sm text-slate-500">
              ※個別の医療相談・診断は受け付けておりません。
            </p>
          </div>
        </article>
      </main>
      <Footer categories={categories} />
    </>
  );
}
