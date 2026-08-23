/**
 * 英語セクションのSEO定義（ページ一覧・canonical・sitemap・robots）
 *
 * ページ側に直書きせずここへ集めているのは、テストから素の値として
 * 検証できるようにするため。React Server Component は node --test から
 * 直接は検証しづらいので、検証したい事実（canonical・sitemap登録・
 * 検索結果を index させない）は素のデータに落としておく。
 *
 * このファイルは他の .ts をランタイムimportしない（core.ts と同じ理由）。
 */

import type { MetadataRoute } from "next";

export const SITE_ORIGIN = "https://camp-gear-lab.com";

/** 英語セクションの言語タグ。`<html lang>` ではなくラッパー要素に付ける（理由は layout 側のコメント） */
export const EN_LANG = "en-US";

export type EnPagePath =
  | "/en"
  | "/en/tools/snow-peak-igt-model-finder"
  | "/en/guides/snow-peak-igt-model-numbers"
  | "/en/methodology"
  | "/en/affiliate-disclosure";

export type EnPage = {
  path: EnPagePath;
  title: string;
  description: string;
  /** sitemap に載せる = index させたいページ */
  indexable: boolean;
  priority: number;
  changeFrequency: "daily" | "weekly" | "monthly" | "yearly";
};

export const EN_PAGES: EnPage[] = [
  {
    path: "/en",
    title: "Snow Peak IGT reference for English-speaking users",
    description:
      "An experiment: a small English reference for Snow Peak IGT model numbers, discontinued products, confirmed successors and officially documented compatibility.",
    indexable: true,
    priority: 0.6,
    changeFrequency: "weekly",
  },
  {
    path: "/en/tools/snow-peak-igt-model-finder",
    title: "Snow Peak IGT Model Finder",
    description:
      "Search a Snow Peak IGT model number or product name to see the Japanese and US model numbers, whether it is current or discontinued, any confirmed successor, and compatibility that is documented by Snow Peak.",
    indexable: true,
    priority: 0.7,
    changeFrequency: "weekly",
  },
  {
    path: "/en/guides/snow-peak-igt-model-numbers",
    title: "Understanding Snow Peak IGT model numbers",
    description:
      "Why Japanese and US Snow Peak IGT model numbers differ, why a successor product is not the same as a compatible product, and how to check compatibility against official documentation.",
    indexable: true,
    priority: 0.6,
    changeFrequency: "monthly",
  },
  {
    path: "/en/methodology",
    title: "Methodology",
    description:
      "Which sources this English section uses, how records are verified, how verification dates are handled, and why unknown information is left marked as unknown.",
    indexable: true,
    priority: 0.4,
    changeFrequency: "monthly",
  },
  {
    path: "/en/affiliate-disclosure",
    title: "Affiliate disclosure",
    description:
      "How Camp Gear Lab handles affiliate links in this English section, and what the links do and do not mean.",
    indexable: true,
    priority: 0.3,
    changeFrequency: "yearly",
  },
];

export function getEnPage(path: EnPagePath): EnPage {
  const page = EN_PAGES.find((p) => p.path === path);
  if (!page) throw new Error(`Unknown English page: ${path}`);
  return page;
}

/** 自己参照canonical。相対パスで返す（Next の metadataBase が絶対化する） */
export function enCanonical(path: EnPagePath): string {
  return path;
}

export function enAbsoluteUrl(path: EnPagePath): string {
  return `${SITE_ORIGIN}${path}`;
}

/**
 * sitemap に載せる英語ページ。
 *
 * 対応する日本語版ページが存在しないので **hreflang（alternates.languages）は
 * 一切生成しない**。存在しない対応先を宣言すると、Googleは相互参照が取れず
 * 無視するどころか誤ったシグナルになる。
 */
export function enSitemapEntries(lastModified: Date): MetadataRoute.Sitemap {
  return EN_PAGES.filter((p) => p.indexable).map((p) => ({
    url: enAbsoluteUrl(p.path),
    lastModified,
    changeFrequency: p.changeFrequency,
    priority: p.priority,
  }));
}

/**
 * Finder の robots 指定。
 *
 * 検索結果は同一ページ内で描画し、型番ごとのURLは作らない。
 * それでも `?q=` 付きのURLは共有・リンクされうるので、クエリが付いた
 * リクエストは noindex にする。ここを開けると「検索語の数だけ薄いページが
 * indexされる」低品質プログラマティックSEOになる。
 */
export function finderRobots(hasQuery: boolean): { index: boolean; follow: boolean } {
  return hasQuery ? { index: false, follow: true } : { index: true, follow: true };
}

/** searchParams からクエリが付いているかを判定する（配列で来る場合も拾う） */
export function hasSearchQuery(
  searchParams: Record<string, string | string[] | undefined> | undefined
): boolean {
  const q = searchParams?.q;
  if (Array.isArray(q)) return q.some((v) => typeof v === "string" && v.trim() !== "");
  return typeof q === "string" && q.trim() !== "";
}
