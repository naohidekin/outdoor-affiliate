import type { Metadata } from "next";
import { toJsonLd } from "@/lib/jsonld";
import Link from "next/link";
import { notFound } from "next/navigation";
import {
  getPublicCategories,
  getCategoryBySlug,
  getArticlesByCategory,
  getProductsByIds,
} from "@/lib/db";
import Header from "@/components/Header";
import Footer from "@/components/Footer";
import ArticleCard from "@/components/ArticleCard";
import { getCategoryIcon } from "@/lib/category-icons";

const CATEGORY_INTRO: Record<string, string> = {
  tent: "テント選びは、キャンプ全体の快適さを左右する最重要ポイントです。僕がキャンプを始めた頃、「安いテントで十分だろう」と格安テントを購入したのですが、初めての雨でフロアが水浸しになってひどい思いをしました。耐水圧・設営のしやすさ・重量・サイズ感の4つを軸に選べば、後悔しない一張りに出会えます。ファミリー向けの大型モデルからソロに最適な軽量テントまで、用途と予算別に徹底比較しています。はじめての一張り選びにも、ギアのアップグレードにもぜひ参考にしてください。",
  light:
    "ランタン選びはそれほど難しくありません。用途を決めれば、答えはほぼ見えてきます。サイト全体を照らすメインランタン、テーブルを照らすサブランタン、就寝用のテント内ランタン──この3役を意識して選ぶのが鉄板です。僕は最初、1つのランタンで全部まかなおうとして暗くて不便な思いをしました。今は役割ごとに3つ使い分けています。ガス・LEDそれぞれのメリットと、明るさ・燃焼時間・重量を比較してご紹介しています。",
  "sleeping-bag":
    "シュラフ選びで最も大事なのは「使用可能温度域」です。寒すぎるシュラフで眠れなかった経験は、キャンプをやっていれば誰でも一度はあるはず。僕も初年度に10℃対応のシュラフで5月の東京近郊の山間キャンプ場に行き、夜中に目が覚めて震えながら朝を待った苦い思い出があります。封筒型とマミー型の違い、化繊とダウンの使い分け、快適温度の見方まで、初心者でも分かるように解説しています。季節と予算に合った最適な一枚を見つけてください。",
  burner:
    "バーナー選びは「OD缶かCB缶か」をまず決めることが大事です。OD缶は高山や寒冷地でも安定した火力が出る一方、価格が高め。CB缶はコンビニで買えるコスパの良さが魅力です。僕はソロキャンプ用にシングルバーナー、家族キャンプ用にツーバーナーと使い分けています。火力・収納性・安定性・コスパを軸に、用途別のおすすめモデルを比較しました。「料理にこだわりたい」という方から「お湯が沸けば十分」という方まで、最適な一台が見つかるはずです。",
  backpack:
    "バックパック選びで後悔しやすいのが「容量のミス」です。少なすぎると荷物が入りきらず、大きすぎると無駄に重くなります。日帰りなら20〜30L、テント泊なら50〜60Lが目安です。僕が最初に買ったザックは背面長が合っておらず、長時間背負うと肩が痛くて登山が楽しめませんでした。容量・背面長・ウエストベルト・通気性の4点を確認すれば、体に合ったザックに出会えます。用途別のおすすめモデルを比較してご紹介しています。",
  wear: "レインウェアは「守備の要」です。山の天候は急変するので、性能の低いウェアを着ていると本当に危ない場面があります。一方、キャンプやフェスなら1万円台のモデルで十分ですよ。僕はゴアテックスを買う前に格安ウェアで何度も滲みを経験し、結局買い直す羽目になりました。最初から用途に合ったものを選ぶほうがコスパは高いです。耐水圧・透湿性・重量の数値の読み方と、用途別のおすすめモデルを詳しく解説しています。",
  shoes:
    "トレッキングシューズは足元の安全を守るための最重要ギアです。ローカットは軽快で歩きやすいですが、捻挫リスクが高め。ミッドカットは安定感があり、初心者に最適です。僕は登山を始めた当初、スニーカーで岩場を歩いてソールが滑って転倒した苦い経験があります。それ以来、登山専用シューズの重要性を身に染みて感じています。ゴアテックスの必要性・サイズ選びのコツ・価格帯別のおすすめモデルまで、初めての一足選びを徹底サポートします。",
  firepit:
    "焚き火台はキャンプの夜を特別にする最高のギアです。ほとんどのキャンプ場では直火禁止になっているので、焚き火台は今や必須装備といえます。僕がキャンプを始めた頃は焚き火台を持っておらず、直火OKのキャンプ場ばかり探していましたが、焚き火台を導入してからサイト選びの自由度が一気に上がりました。素材・重量・二次燃焼機能の有無など、選ぶポイントを押さえてご紹介しています。ソロからファミリーまで最適な一台が見つかります。",
  tarp: "タープはテントと並ぶキャンプの必需品です。日差しや雨からリビングスペースを守り、開放的な空間を作れます。「最初はテントだけでいいや」と思っていた僕も、雨の日にタープなしで過ごして懲りました。設営がやや難しいイメージを持つ方もいますが、ヘキサタープなら初心者でも30分あれば立てられます。ヘキサ・レクタ・ウイングの形状の違い、素材の選び方、ポールとの組み合わせまで、用途別に最適なモデルをご紹介しています。",
  chair:
    "キャンプチェアはキャンプ中に最も長時間使うギアです。座り心地が悪いと腰が痛くなり、せっかくのキャンプが台無しになります。最初に安いチェアを買って失敗した経験から、「チェアは妥協しないほうがいい」と強く思っています。ハイスタイルは食事しやすく、ロースタイルは焚き火に近くてリラックス感が高い。自分のキャンプスタイルに合ったものを選ぶのが大事です。軽量モデルからリラックス特化まで、座り心地と予算別に比較しています。",
  table:
    "キャンプテーブルは調理・食事・団らんの中心になるギアです。「高さ」を間違えると、椅子との相性が悪くなって使いにくくなります。ハイチェアを使うならハイテーブル、ロースタイルならローテーブルが基本。僕は最初にローテーブルを1つ買ったはいいのですが、子供たちにとって高さが合わず買い直した経験があります。アルミ・木・ステンレスの素材の違い、人数に合った奥行き・幅の目安まで、用途別に最適なテーブルをご紹介しています。",
  cooler:
    "クーラーボックスは夏キャンプの生命線です。食材管理を甘く見ると食中毒のリスクがありますし、飲み物がぬるくなればテンションも下がります。「安いクーラーで十分」と思っていた頃、2日目にビールがぬるくなって後悔した記憶があります。ハードクーラーとソフトクーラーの使い分け、保冷力の正しい見方、容量の選び方まで解説しています。1泊2日から連泊まで、人数別・スタイル別のおすすめモデルを比較しています。",
  "insect-repellent":
    "虫対策はキャンプの快適さを大きく左右します。特に夏の夜、対策が不十分だとブヨやヤブ蚊の猛攻で眠れないほど辛い思いをします。僕も東京近郊のキャンプ場でブヨに顔を何か所も刺され、翌日腫れて帰った苦い経験があります。それ以来、虫除けスプレー・線香・ランタン型忌避剤を組み合わせて使うようになりました。スプレーの成分（DEET・イカリジン）の違い、子供への安全な使い方、ブヨ・蚊・アブそれぞれの対策まで、実体験をもとに詳しく解説しています。",
  tumbler:
    "タンブラーとボトルは、アウトドアでの飲み物の温度を長時間キープするための重要なギアです。コーヒー好きの僕にとって、山頂や焚き火前で熱いコーヒーを飲む瞬間はキャンプの至福タイムです。そのためには保温性能の高いステンレス製タンブラーが欠かせません。ナルゲン・サーモス・スタンレー・モンベルなど人気ブランドを保温力・容量・重量・使いやすさで徹底比較。アウトドアでの用途別に最適なモデルをご紹介しています。",
};


export const revalidate = 21600; // ISR: 6時間（Egress削減・2026-07-24）

export async function generateMetadata({
  params,
}: {
  params: Promise<{ slug: string }>;
}): Promise<Metadata> {
  const { slug } = await params;
  const category = await getCategoryBySlug(slug);
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
      siteName: "Camp Gear Lab",
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
  const category = await getCategoryBySlug(slug);
  if (!category) notFound();

  const [categories, articles] = await Promise.all([
    getPublicCategories(),
    getArticlesByCategory(category.id),
  ]);
  // 公開記事が無いカテゴリは表示するものが無い。薄いページを配信・
  // インデックスさせないため404にする（記事が入れば自動的に復活する）
  if (articles.length === 0) notFound();

  const allProductIds = [...new Set(articles.flatMap((a) => a.productIds))];
  const allProducts = allProductIds.length > 0
    ? await getProductsByIds(allProductIds)
    : [];
  const productMap = new Map(allProducts.map((p) => [p.id, p]));
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
        dangerouslySetInnerHTML={{ __html: toJsonLd(breadcrumbJsonLd) }}
      />
      <script
        type="application/ld+json"
        dangerouslySetInnerHTML={{ __html: toJsonLd(itemListJsonLd) }}
      />
      <Header categories={categories} />
      <main className="flex-1">
        <section className="bg-white border-b border-line">
          <div className="max-w-6xl mx-auto px-4 py-10 md:py-14">
            <nav className="text-sm text-slate-500 mb-5" aria-label="パンくず">
              <Link href="/" className="hover:text-lake-600 transition">
                ホーム
              </Link>
              <span className="mx-2 text-slate-400">/</span>
              <span className="text-slate-600">{category.name}</span>
            </nav>
            <div className="flex items-center gap-4">
              <div className="w-14 h-14 rounded-xl bg-lake-50 border border-lake-100 flex items-center justify-center text-lake-600">
                {getCategoryIcon(category.slug, "lg")}
              </div>
              <div>
                <h1 className="text-3xl md:text-4xl font-semibold tracking-tight text-ink-strong">
                  {category.name}
                </h1>
                <p className="text-slate-600 mt-1.5 text-sm md:text-base">
                  {category.description}
                </p>
              </div>
            </div>
          </div>
        </section>

        {introText && (
          <section className="max-w-6xl mx-auto px-4 pt-10 pb-2">
            <p className="text-gray-600 leading-relaxed">{introText}</p>
          </section>
        )}

        <section className="max-w-6xl mx-auto px-4 py-12">
          {articles.length > 0 ? (() => {
            const guides = articles.filter(a => /guide|checklist|first-time|safety/.test(a.slug));
            const comparisons = articles.filter(a => !guides.includes(a) && /vs|比較|showdown/i.test(a.title));
            const rankings = articles.filter(a => !guides.includes(a) && !comparisons.includes(a) && /おすすめ|ランキング/.test(a.title));
            const others = articles.filter(a => !guides.includes(a) && !comparisons.includes(a) && !rankings.includes(a));

            const renderGrid = (items: typeof articles) => (
              <div className="grid sm:grid-cols-2 lg:grid-cols-3 gap-5">
                {items.map((article) => (
                  <ArticleCard
                    key={article.id}
                    article={article}
                    category={category}
                    thumbnailProduct={article.productIds
                      .map((id) => productMap.get(id))
                      .find((p) => p?.imageUrl)}
                  />
                ))}
              </div>
            );

            return (
              <div className="space-y-14">
                {guides.length > 0 && (
                  <div>
                    <h3 className="text-lg font-semibold text-ink-strong mb-1 flex items-center gap-2">
                      まず読むべきガイド
                    </h3>
                    <p className="text-sm text-slate-500 mb-4">入門・基礎知識から始めたい方へ</p>
                    {renderGrid(guides)}
                  </div>
                )}
                {comparisons.length > 0 && (
                  <div>
                    <h3 className="text-lg font-semibold text-ink-strong mb-1 flex items-center gap-2">
                      比較・VS記事
                    </h3>
                    <p className="text-sm text-slate-500 mb-4">製品を徹底的に比べたい方へ</p>
                    {renderGrid(comparisons)}
                  </div>
                )}
                {rankings.length > 0 && (
                  <div>
                    <h3 className="text-lg font-semibold text-ink-strong mb-1 flex items-center gap-2">
                      おすすめランキング
                    </h3>
                    <p className="text-sm text-slate-500 mb-4">どれを選べばいいか迷っている方へ</p>
                    {renderGrid(rankings)}
                  </div>
                )}
                {others.length > 0 && (
                  <div>
                    {(guides.length > 0 || comparisons.length > 0 || rankings.length > 0) && (
                      <h3 className="text-lg font-semibold text-ink-strong mb-1 flex items-center gap-2">
                        その他の記事
                      </h3>
                    )}
                    {(guides.length > 0 || comparisons.length > 0 || rankings.length > 0) && (
                      <p className="text-sm text-slate-500 mb-4">関連する記事・レビューなど</p>
                    )}
                    {renderGrid(others)}
                  </div>
                )}
              </div>
            );
          })() : (
            <div className="text-center py-16">
              <p className="text-slate-400 text-lg">
                このカテゴリにはまだ記事がありません
              </p>
            </div>
          )}
        </section>
      </main>
      <Footer categories={categories} />
    </>
  );
}
