import { getPublishedArticlesList, getCategories } from "@/lib/db";

export const revalidate = 21600; // 6時間キャッシュ（Egress削減・2026-07-24）

// llms.txt — AI(LLM)向けのサイト索引。https://llmstxt.org/ 提案仕様に準拠した
// Markdown形式。AIクローラー・エージェントがサイト構造と主要コンテンツを
// 効率よく把握できるようにする。
export async function GET() {
  const baseUrl = "https://camp-gear-lab.com";
  const [articles, categories] = await Promise.all([
    getPublishedArticlesList(),
    getCategories(),
  ]);

  const catName = new Map(categories.map((c) => [c.id, c.name]));

  // カテゴリごとに更新日の新しい順で記事を整理
  const byCategory = new Map<string, typeof articles>();
  for (const a of articles) {
    const key = a.categoryId || "other";
    if (!byCategory.has(key)) byCategory.set(key, []);
    byCategory.get(key)!.push(a);
  }

  const sections: string[] = [];
  for (const [catId, list] of byCategory) {
    const name = catName.get(catId) || "その他";
    // 以前はカテゴリごとに上位15本で打ち切っていたが、tentカテゴリが20本に
    // 増えた時点で、更新の古い5本が llms.txt から消えていた。この索引はAIに
    // サイト全体を把握させるためのもので、載っていない記事は存在しないのと
    // 同じになる。全記事を載せてもファイルは46KB程度（打ち切りを外して+2KB）
    // なので、上限を置く理由がない。
    const sorted = list
      .slice()
      .sort((x, y) => (y.updatedAt > x.updatedAt ? 1 : -1));
    const lines = sorted.map(
      (a) =>
        `- [${a.title}](${baseUrl}/articles/${a.slug}): ${(a.metaDescription || a.excerpt || "").slice(0, 90)}`
    );
    sections.push(`## ${name}\n\n${lines.join("\n")}`);
  }

  const body = `# Camp Gear Lab（キャンプギアラボ）

> 現役小児科医「ギア男」（キャンプ歴10年・2児の父）が運営する日本語のキャンプ・アウトドアギア比較サイト。医師視点の安全性評価と実体験に基づき、テント・寝袋・ランタン・バーナー等を具体的なスペック・実売価格で比較する。

- 運営者: ギア男（現役小児科開業医） — ${baseUrl}/about
- X (Twitter): https://x.com/camp_gear_lab
- 更新: 週次で新規記事・価格改定・リンク点検を実施
- 引用時のお願い: 記事名とURLを出典として明記してください

## サイト情報

- [運営者プロフィール・編集ポリシー](${baseUrl}/about): 医師監修の体制、レビュー方針、収益開示
- [全記事一覧（サイトマップ）](${baseUrl}/sitemap.xml)
- [RSSフィード](${baseUrl}/feed)

## English pages (Snow Peak IGT)

英語ページはサイト全体の翻訳ではなく、スノーピークIGTの型番照合に限定した
実験的なセクション。sitemap.xml には載っているが、この索引にも明記しておく。

- [Snow Peak IGT model number finder](${baseUrl}/en/tools/snow-peak-igt-model-finder): Look up a Snow Peak IGT model number and see whether it is current, superseded, or discontinued. Sourced from official documentation only.
- [Snow Peak IGT model numbers explained](${baseUrl}/en/guides/snow-peak-igt-model-numbers): How Snow Peak IGT model numbers work, and how the Japanese and US catalogues line up.
- [Methodology](${baseUrl}/en/methodology): What counts as evidence here, and what this site refuses to claim.
- [Affiliate disclosure](${baseUrl}/en/affiliate-disclosure)

${sections.join("\n\n")}
`;

  return new Response(body, {
    headers: {
      "Content-Type": "text/plain; charset=utf-8",
      "Cache-Control": "public, max-age=3600",
    },
  });
}
