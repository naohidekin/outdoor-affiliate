import type { Metadata } from "next";
import Link from "next/link";
import { notFound } from "next/navigation";
import {
  getCategories,
  getCategoryBySlug,
  getArticlesByCategory,
} from "@/lib/db";
import Header from "@/components/Header";
import Footer from "@/components/Footer";

const CATEGORY_INTRO: Record<string, string> = {
  tent: "テント選びはキャンプの快適さを左右する最も重要なポイントだ。ファミリー向けの大型テントからソロキャンプ用の軽量モデルまで、用途と人数に合った最適な一張りを見つけよう。設営のしやすさ・耐水圧・重量・価格を徹底比較し、後悔しないテント選びをサポートする。",
  light:
    "ランタン・ライトはキャンプの夜を快適にする必須ギア。メインサイト用のガスランタンからテント内用のLEDランタンまで、用途別に最適な明るさ・燃料タイプを解説。明るさ（ルーメン）・燃焼時間・重量を比較し、シーン別のベストな選択を提案する。",
  "sleeping-bag":
    "シュラフ（寝袋）は快適な睡眠を左右するキャンプの要。封筒型 vs マミー型、化繊 vs ダウン、対応温度域の選び方を解説。子供用からNANGAなどの高級ダウンシュラフまで、予算と使用シーズンに合った最適な一品を見つけよう。",
  burner:
    "バーナー・コンロは野外調理の心臓部。シングルバーナーのOD缶/CB缶の違いから、ファミリー向けツーバーナーの選び方まで徹底比較。火力・安定性・携帯性・コスパを軸に、ソロからグループまで最適なバーナーを提案する。",
  backpack:
    "登山・ハイキング用バックパックは体への負担を左右する重要ギア。日帰り20L〜テント泊60Lまで、容量別の選び方を解説。背面長のフィッティング、ウエストベルト、通気性など、長時間背負っても疲れにくいザックの選び方をガイドする。",
  wear: "レインウェア・アウトドアウェアは山の天候変化から身を守る命綱。ゴアテックスと格安素材の違い、耐水圧・透湿性の数値の読み方を解説。登山・キャンプ・普段使いまでカバーできるコスパの良いウェアをランキング形式で紹介する。",
  shoes:
    "登山靴・トレッキングシューズは足元の安全と快適さを決める最重要ギア。ローカット vs ミッドカットの違い、ゴアテックスの必要性、サイズ選びのコツを解説。初心者向けの歩きやすいモデルから本格登山靴まで比較し、最初の一足選びをサポートする。",
  firepit:
    "焚き火台はキャンプの夜を特別にする定番ギア。ソロ用のコンパクトモデルからファミリー向けの大型タイプまで、素材・重量・組み立てやすさ・二次燃焼機能を比較。直火禁止のキャンプ場が増える今、焚き火台は必須装備だ。",
};

export const dynamic = "force-dynamic";

export async function generateMetadata({
  params,
}: {
  params: Promise<{ slug: string }>;
}): Promise<Metadata> {
  const { slug } = await params;
  const category = getCategoryBySlug(slug);
  if (!category) return {};

  return {
    title: `${category.name}のおすすめ比較・レビュー`,
    description: `${category.description}おすすめ製品の比較・口コミ・ランキング情報をまとめて紹介。`,
    alternates: {
      canonical: `/category/${category.slug}`,
    },
    openGraph: {
      title: `${category.name}のおすすめ比較・レビュー`,
      description: `${category.description}おすすめ製品の比較・口コミ・ランキング情報をまとめて紹介。`,
      siteName: "Outdoor Gear Lab",
      locale: "ja_JP",
      url: `/category/${category.slug}`,
    },
  };
}

export default async function CategoryPage({
  params,
}: {
  params: Promise<{ slug: string }>;
}) {
  const { slug } = await params;
  const category = getCategoryBySlug(slug);
  if (!category) notFound();

  const categories = getCategories();
  const articles = getArticlesByCategory(category.id);
  const baseUrl = "https://camp-gear-lab.com";
  const introText = CATEGORY_INTRO[category.slug] ?? "";

  const breadcrumbJsonLd = {
    "@context": "https://schema.org",
    "@type": "BreadcrumbList",
    itemListElement: [
      { "@type": "ListItem", position: 1, name: "ホーム", item: baseUrl },
      {
        "@type": "ListItem",
        position: 2,
        name: category.name,
        item: `${baseUrl}/category/${category.slug}`,
      },
    ],
  };

  const itemListJsonLd = {
    "@context": "https://schema.org",
    "@type": "CollectionPage",
    name: `${category.name}のおすすめ比較・レビュー`,
    url: `${baseUrl}/category/${category.slug}`,
    description: `${category.description}おすすめ製品の比較・口コミ・ランキング情報。`,
    mainEntity: {
      "@type": "ItemList",
      itemListElement: articles.map((a, i) => ({
        "@type": "ListItem",
        position: i + 1,
        url: `${baseUrl}/articles/${a.slug}`,
        name: a.title,
      })),
    },
  };

  return (
    <>
      <script
        type="application/ld+json"
        dangerouslySetInnerHTML={{ __html: JSON.stringify(breadcrumbJsonLd) }}
      />
      <script
        type="application/ld+json"
        dangerouslySetInnerHTML={{ __html: JSON.stringify(itemListJsonLd) }}
      />
      <Header categories={categories} />
      <main className="flex-1">
        <section className="bg-green-700 text-white py-12">
          <div className="max-w-6xl mx-auto px-4">
            <nav className="text-green-200 text-sm mb-2">
              <Link href="/" className="hover:text-white">
                ホーム
              </Link>{" "}
              / {category.name}
            </nav>
            <h1 className="text-3xl font-bold">{category.name}</h1>
            <p className="text-green-200 mt-2">{category.description}</p>
          </div>
        </section>

        {introText && (
          <section className="max-w-6xl mx-auto px-4 pt-10 pb-2">
            <p className="text-gray-700 leading-relaxed">{introText}</p>
          </section>
        )}

        <section className="max-w-6xl mx-auto px-4 py-12">
          {articles.length > 0 ? (
            <div className="grid sm:grid-cols-2 lg:grid-cols-3 gap-6">
              {articles.map((article) => (
                <Link
                  key={article.id}
                  href={`/articles/${article.slug}`}
                  className="bg-white rounded-xl shadow-sm hover:shadow-md transition p-6 border border-gray-100"
                >
                  <h3 className="font-bold text-gray-800 mb-2 line-clamp-2">
                    {article.title}
                  </h3>
                  <p className="text-sm text-gray-500 line-clamp-3">
                    {article.excerpt}
                  </p>
                  <p className="text-xs text-gray-400 mt-3">
                    {article.publishedAt &&
                      new Date(article.publishedAt).toLocaleDateString("ja-JP")}
                  </p>
                </Link>
              ))}
            </div>
          ) : (
            <div className="text-center py-16">
              <p className="text-gray-400 text-lg">
                このカテゴリにはまだ記事がありません
              </p>
            </div>
          )}
        </section>
      </main>
      <Footer />
    </>
  );
}
