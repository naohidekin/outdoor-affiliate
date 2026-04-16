#!/usr/bin/env node
/**
 * 内部リンク追加スクリプト
 * 孤立しているページへの内部リンクを関連記事に追加する
 */
import { readJson, writeJson } from "../src/lib/x-agent-utils.mjs";

const articles = readJson("articles.json");

// 追加するリンクのマッピング: targetSlug の記事に fromSlug からリンクを追加
const linkAdditions = [
  // solo-tarp-ranking へのリンク
  {
    fromSlug: "tarp-ranking",
    addLink: {
      text: "ソロキャンプ向けタープおすすめ4選｜ウイング・レクタ・車連結タイプ別に比較",
      slug: "solo-tarp-ranking",
    },
  },
  // compact-chair-ranking へのリンク
  {
    fromSlug: "camp-chair-ranking",
    addLink: {
      text: "軽量・コンパクトアウトドアチェアおすすめ5選｜ソロキャン・登山兼用で選ぶ",
      slug: "compact-chair-ranking",
    },
  },
  {
    fromSlug: "rainwear-ranking",
    addLink: {
      text: "軽量・コンパクトアウトドアチェアおすすめ5選｜ソロキャン・登山兼用で選ぶ",
      slug: "compact-chair-ranking",
    },
  },
  // summer-camp-cooler-tips へのリンク
  {
    fromSlug: "cooler-box-ranking",
    addLink: {
      text: "夏キャンプのクーラーボックス選び【保冷力・容量・予算別】失敗しない選び方と使い方",
      slug: "summer-camp-cooler-tips",
    },
  },
  {
    fromSlug: "soft-cooler-ranking",
    addLink: {
      text: "夏キャンプのクーラーボックス選び【保冷力・容量・予算別】失敗しない選び方と使い方",
      slug: "summer-camp-cooler-tips",
    },
  },
  // winter-camp-beginners-checklist へのリンク
  {
    fromSlug: "camping-beginner-gear-checklist",
    addLink: {
      text: "冬キャンプ初心者の持ち物チェックリスト【防寒・安全対策を徹底解説】",
      slug: "winter-camp-beginners-checklist",
    },
  },
  {
    fromSlug: "nanga-sleeping-bag-comparison",
    addLink: {
      text: "冬キャンプ初心者の持ち物チェックリスト【防寒・安全対策を徹底解説】",
      slug: "winter-camp-beginners-checklist",
    },
  },
  // winter-sleeping-bag-ranking へのリンク
  {
    fromSlug: "nanga-sleeping-bag-comparison",
    addLink: {
      text: "冬キャンプ用シュラフおすすめ比較【NANGA vs モンベル vs コスパ系】快適温度の見方も解説",
      slug: "winter-sleeping-bag-ranking",
    },
  },
  {
    fromSlug: "budget-sleeping-bag-ranking",
    addLink: {
      text: "冬キャンプ用シュラフおすすめ比較【NANGA vs モンベル vs コスパ系】快適温度の見方も解説",
      slug: "winter-sleeping-bag-ranking",
    },
  },
  {
    fromSlug: "spring-sleeping-bag-guide",
    addLink: {
      text: "冬キャンプ用シュラフおすすめ比較【NANGA vs モンベル vs コスパ系】快適温度の見方も解説",
      slug: "winter-sleeping-bag-ranking",
    },
  },
  // gw-camp-checklist-2026 へのリンク
  {
    fromSlug: "gw-camp-guide-2026",
    addLink: {
      text: "GWキャンプ直前チェックリスト｜忘れ物ゼロで出発する15項目",
      slug: "gw-camp-checklist-2026",
    },
  },
  {
    fromSlug: "gw-camping-gear-budget",
    addLink: {
      text: "GWキャンプ直前チェックリスト｜忘れ物ゼロで出発する15項目",
      slug: "gw-camp-checklist-2026",
    },
  },
  // family-camp-first-time-guide へのリンク
  {
    fromSlug: "family-tent-ranking",
    addLink: {
      text: "初めてのファミリーキャンプ完全ガイド｜子連れで失敗しない7つのコツ",
      slug: "family-camp-first-time-guide",
    },
  },
  {
    fromSlug: "camping-beginner-gear-checklist",
    addLink: {
      text: "初めてのファミリーキャンプ完全ガイド｜子連れで失敗しない7つのコツ",
      slug: "family-camp-first-time-guide",
    },
  },
];

let updated = 0;
let skipped = 0;

for (const { fromSlug, addLink } of linkAdditions) {
  const art = articles.find((a) => a.slug === fromSlug);
  if (!art) {
    console.log(`⚠️  記事が見つかりません: ${fromSlug}`);
    skipped++;
    continue;
  }

  // すでにリンクが存在するか確認
  if (art.content.includes(`/articles/${addLink.slug}`)) {
    console.log(`⏭  スキップ (既にリンクあり): ${fromSlug} → ${addLink.slug}`);
    skipped++;
    continue;
  }

  // 「## 関連記事」セクションを探して末尾にリンクを追加
  const relatedSection = "## 関連記事";
  const newLink = `- [${addLink.text}](/articles/${addLink.slug})`;

  if (art.content.includes(relatedSection)) {
    // 「## 関連記事」の末尾（次の##セクション or ファイル末尾）を探す
    const idx = art.content.indexOf(relatedSection);
    // セクション末尾を探す（次の##か文末）
    const afterSection = art.content.slice(idx + relatedSection.length);
    const nextSectionIdx = afterSection.search(/\n## /);
    if (nextSectionIdx === -1) {
      // 「## 関連記事」が最後のセクション → 末尾に追加
      art.content = art.content.trimEnd() + "\n" + newLink + "\n";
    } else {
      // 次のセクションの前に挿入
      const insertAt = idx + relatedSection.length + nextSectionIdx;
      art.content =
        art.content.slice(0, insertAt).trimEnd() +
        "\n" +
        newLink +
        "\n" +
        art.content.slice(insertAt);
    }
  } else {
    // 「## 関連記事」セクションがない → 末尾に追加
    art.content =
      art.content.trimEnd() +
      "\n\n## 関連記事\n\n" +
      newLink +
      "\n";
  }

  art.updatedAt = new Date().toISOString();
  console.log(`✅ リンク追加: ${fromSlug} → ${addLink.slug}`);
  updated++;
}

writeJson("articles.json", articles);
console.log(`\n完了: ${updated}件追加, ${skipped}件スキップ`);
