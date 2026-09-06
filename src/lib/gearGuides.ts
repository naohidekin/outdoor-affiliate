import type { Article } from "./types.ts";

/** Editorial routes through existing articles; never publish database drafts here. */
export const GEAR_GUIDES = [
  {
    id: "sleep", label: "家族の寝具を選ぶ", shortLabel: "寝袋・マット・枕",
    description: "寝床の広さから考えると、買い足す道具が見えてきます。",
    categoryIds: ["sleeping-bag"],
    checks: ["テントに家族分の寝具を敷けるか", "車に積める収納サイズか", "手入れと片付けを続けられるか"],
    links: [
      { slug: "cot-vs-mat-comparison", label: "コットとマット、寝床の作り方を比べる", detail: "高さ・設置面積・収納から、寝床の土台を決める。" },
      { slug: "kids-sleeping-bag-ranking", label: "子供用寝袋のサイズと使い勝手を比べる", detail: "体格、使う季節、洗濯方法を確認する。" },
      { slug: "camp-pillow-ranking", label: "キャンプ枕のタイプを比べる", detail: "高さ調整と持ち運びやすさから絞る。" },
    ],
  },
  {
    id: "tent", label: "家族のテントを選ぶ", shortLabel: "広さ・設営・買い替え",
    description: "定員の数字だけで決めず、寝具と荷物を置いた後の広さまで。",
    categoryIds: ["tent", "tarp"],
    checks: ["寝室に家族分の寝具が収まるか", "張り綱と車を含めて区画に入るか", "設営・撤収と積載を無理なくできるか"],
    links: [
      { slug: "family-tent-ranking", label: "初めてのファミリーテントを絞る", detail: "形・広さ・予算から候補を見つける。" },
      { slug: "landlock-vs-landnest-shelter", label: "ランドロックとランドネストを比べる", detail: "寝室、リビング、設営の負担を見比べる。" },
      { slug: "snow-peak-amenity-dome-l-10year-review", label: "アメニティドームLの長期使用記録を読む", detail: "使い続けて感じた点と、買い替えの判断を読む。" },
      { slug: "tarp-tent-layout-site-guide", label: "テントとタープの配置を考える", detail: "区画内の動線と、必要なスペースを確認する。" },
    ],
  },
  {
    id: "light", label: "夜の明かりを整える", shortLabel: "LEDランタン・スタンド",
    description: "テーブル、寝室、移動用。照らしたい場所を決めてから選びます。",
    categoryIds: ["light"],
    checks: ["使う場所に合わせて明るさを調整できるか", "必要な時間使える電源方式か", "取付方法と置き場所を確保できるか"],
    links: [
      { slug: "led-lantern-ranking", label: "充電式と乾電池式のLEDランタンを比べる", detail: "明るさと電源方式から選ぶ。" },
      { slug: "lantern-stand-ranking", label: "ランタンの置き方・吊り下げ方を考える", detail: "スタンドの設置方法と対応する重さを確認する。" },
    ],
  },
  {
    id: "cooling", label: "暑い日の装備を見直す", shortLabel: "クーラー・電源・保冷",
    description: "空気を冷やす道具と、食材を保冷する道具を、用途に分けて確認します。",
    categoryIds: ["fan", "portable-power", "cooler"],
    checks: ["キャンプ場の電源・使用ルールに合うか", "排熱や換気のための場所を確保できるか", "食材の保冷に必要な容量を確保できるか"],
    links: [
      { slug: "portable-cooler-fan-guide", label: "ポータブルクーラーの方式と条件を比べる", detail: "消費電力・排熱・設置場所を確認する。" },
      { slug: "portable-power-station-guide", label: "使う機器に合わせてポータブル電源を選ぶ", detail: "出力と容量を分けて考える。" },
      { slug: "cooler-box-ranking", label: "食材用のクーラーボックスを比べる", detail: "ハードとソフト、持ち運ぶ量から選ぶ。" },
    ],
  },
] as const;

export type GearGuideId = (typeof GEAR_GUIDES)[number]["id"];

export function getAvailableGearGuides(articles: Pick<Article, "slug" | "status" | "title">[]) {
  const published = new Map(articles.filter((a) => a.status === "published").map((a) => [a.slug, a]));
  return GEAR_GUIDES.map((guide) => ({
    ...guide,
    links: guide.links.flatMap((link) => {
      const article = published.get(link.slug);
      return article ? [{ ...link, articleTitle: article.title }] : [];
    }),
  })).filter((guide) => guide.links.length > 0);
}
