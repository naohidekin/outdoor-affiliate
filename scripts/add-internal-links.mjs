#!/usr/bin/env node
/**
 * 内部リンク追加スクリプト
 * 孤立しているページへの内部リンクを関連記事に追加する
 */
import { readJson, writeJson } from "../src/lib/x-agent-utils.mjs";

const articles = readJson("articles.json");

// 追加するリンクのマッピング: targetSlug の記事に fromSlug からリンクを追加
const linkAdditions = [
  // 2026-06-11: リンクグラフ実測で発見した孤立記事（被リンク0/発リンク0）の解消
  {
    fromSlug: "tarp-ranking",
    addLink: {
      text: "タープの種類と選び方完全ガイド！形状・素材・サイズ別に徹底解説【2026年版】",
      slug: "tarp-buying-guide",
    },
  },
  {
    fromSlug: "tarp-buying-guide",
    addLink: {
      text: "タープとテントの連結レイアウト実例集【2026年版】サイト別おすすめ配置パターン",
      slug: "tarp-tent-layout-site-guide",
    },
  },
  {
    fromSlug: "tarp-tent-layout-site-guide",
    addLink: {
      text: "タープの張り方完全ガイド｜初心者でもできる基本〜応用5パターン【2026年版】",
      slug: "tarp-setup-guide-for-beginners",
    },
  },
  {
    fromSlug: "firepit-solo-ranking",
    addLink: {
      text: "ピコグリル398 vs Tokyo Camp焚火台｜1万円の差は\"軽さ\"だけか？正直比較",
      slug: "picogrill-vs-tokyocamp-bonfire",
    },
  },
  {
    fromSlug: "picogrill-vs-tokyocamp-bonfire",
    addLink: {
      text: "焚き火台3大定番ガチ比較｜スノーピーク焚火台L vs ユニフレーム ファイアグリル vs コールマン",
      slug: "firepit-3way-showdown",
    },
  },
  {
    fromSlug: "amenity-dome-vs-landnest-dome",
    addLink: {
      text: "スノーピーク アメニティドームL を10年使った正直レビュー【2026年】",
      slug: "snow-peak-amenity-dome-l-10year-review",
    },
  },
  {
    fromSlug: "camp-chair-ranking",
    addLink: {
      text: "キャンプチェア コンパクト・軽量モデルおすすめ3選【2026年版】持ち運びやすさ徹底比較",
      slug: "compact-lightweight-chair-ranking",
    },
  },
  {
    fromSlug: "tent-with-vestibule-ranking",
    addLink: {
      text: "春キャンプのテント選び「前室の広さ」で選ぶおすすめ3選【2026年版】",
      slug: "tent-vestibule-size-ranking",
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
