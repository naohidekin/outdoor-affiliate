import { getPublishedArticles, getCategories } from "@/lib/db";

export const revalidate = 3600; // 1時間キャッシュ

// llms.txt — AI(LLM)向けのサイト索引。https://llmstxt.org/ 提案仕様に準拠した
// Markdown形式。AIクローラー・エージェントがサイト構造と主要コンテンツを
// 効率よく把握できるようにする。
export async function GET() {
  const baseUrl = "https://camp-gear-lab.com";
  const [articles, categories] = await Promise.all([
    getPublishedArticles(),
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
    const sorted = list
      .slice()
      .sort((x, y) => (y.updatedAt > x.updatedAt ? 1 : -1))
      .slice(0, 15); // カテゴリごとに上位15本
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

${sections.join("\n\n")}
`;

  return new Response(body, {
    headers: {
      "Content-Type": "text/plain; charset=utf-8",
      "Cache-Control": "public, max-age=3600",
    },
  });
}
