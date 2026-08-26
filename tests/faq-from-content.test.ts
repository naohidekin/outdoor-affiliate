import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import {
  extractFaqsFromContent,
  FAQ_HEADING_RE,
} from "../src/lib/faq-from-content.ts";

// ─── 表記3パターン ─────────────────────────────────────
// 2026-08-26 時点の公開記事に実在する3通り。どれか1つでも拾えなくなると、
// その表記の記事群から FAQPage が丸ごと消える

test("### 見出し形式のFAQを拾える", () => {
  const faqs = extractFaqsFromContent(
    [
      "## よくある質問",
      "",
      "### Q1. オーロラライトとは別物ですか？",
      "",
      "同一シリーズです。表記が変わっただけです。",
      "",
      "### 何度まで使えますか？",
      "",
      "対応温度はモデルごとに違います。",
    ].join("\n")
  );
  assert.equal(faqs.length, 2);
  assert.equal(faqs[0].question, "オーロラライトとは別物ですか？");
  assert.equal(faqs[0].answer, "同一シリーズです。表記が変わっただけです。");
  assert.equal(faqs[1].question, "何度まで使えますか？");
});

test("**Q. 〜** 太字形式のFAQを拾える", () => {
  const faqs = extractFaqsFromContent(
    [
      "## よくある質問",
      "",
      "**Q. おにやんま君は蚊に効きますか？**",
      "A. 蚊への効果は実感できていません。",
      "",
      "**Q. 洗えますか？**",
      "A. 洗えません。",
    ].join("\n")
  );
  assert.equal(faqs.length, 2);
  assert.equal(faqs[0].question, "おにやんま君は蚊に効きますか？");
  assert.equal(faqs[1].question, "洗えますか？");
});

test("素の Q. 行形式のFAQを拾える（field-rack-ranking の書き方）", () => {
  const faqs = extractFaqsFromContent(
    [
      "## よくある質問",
      "",
      "Q. フィールドラックは何枚あればいいですか？",
      "ファミリーキャンプなら最低2枚、できれば3枚あると快適です。",
      "",
      "Q. 何段まで積めますか？",
      "公式は4段スタッキング推奨です。",
    ].join("\n")
  );
  assert.equal(faqs.length, 2);
  assert.equal(faqs[0].question, "フィールドラックは何枚あればいいですか？");
});

// ─── 整形 ─────────────────────────────────────────────

test("質問の通し番号と回答の A. 記号が落ちる", () => {
  const faqs = extractFaqsFromContent(
    ["## よくある質問", "", "### Q3. 使えますか？", "A. 使えます。"].join("\n")
  );
  assert.equal(faqs[0].question, "使えますか？");
  assert.equal(faqs[0].answer, "使えます。");
});

test("Markdownの装飾・リンク・ショートコードが構造化データに漏れない", () => {
  const faqs = extractFaqsFromContent(
    [
      "## よくある質問",
      "",
      "### **強調**された質問は？",
      "",
      "答えは[この記事](/articles/foo)にあります。**太字**も`コード`も落ちます。",
      "{{product:some-id}}",
    ].join("\n")
  );
  assert.equal(faqs[0].question, "強調された質問は？");
  const a = faqs[0].answer;
  for (const noise of ["**", "`", "{{", "](", "/articles/foo"]) {
    assert.ok(!a.includes(noise), `構造化データに ${noise} が残っている: ${a}`);
  }
  assert.ok(a.includes("この記事"), "リンクのテキストは残すべき");
});

// ─── 範囲の切り出し ───────────────────────────────────

test("FAQセクションの外（次のH2以降）を巻き込まない", () => {
  const faqs = extractFaqsFromContent(
    [
      "## よくある質問",
      "",
      "### 質問ですか？",
      "回答です。",
      "",
      "## まとめ",
      "",
      "### これは質問ではない見出し",
      "まとめの本文です。",
    ].join("\n")
  );
  assert.equal(faqs.length, 1);
  assert.equal(faqs[0].question, "質問ですか？");
});

test("水平線で終わるFAQセクションもそこで切れる", () => {
  const faqs = extractFaqsFromContent(
    [
      "## よくある質問",
      "",
      "Q. 質問ですか？",
      "回答です。",
      "",
      "---",
      "",
      "## まとめ：あとがき",
      "本文。",
    ].join("\n")
  );
  assert.equal(faqs.length, 1);
});

test("FAQセクションが無い本文からは何も取れない", () => {
  assert.deepEqual(extractFaqsFromContent("## 選び方\n\n本文です。"), []);
  assert.deepEqual(extractFaqsFromContent(""), []);
});

test("回答が無い質問は捨てる（見出しだけ拾って空の回答を出さない）", () => {
  const faqs = extractFaqsFromContent(
    ["## よくある質問", "", "### 回答のない質問？", "", "### 回答のある質問？", "こちらには回答があります。"].join("\n")
  );
  assert.equal(faqs.length, 1);
  assert.equal(faqs[0].question, "回答のある質問？");
});

// ─── ページ側との接続 ─────────────────────────────────

const PAGE = fs.readFileSync(
  path.join(process.cwd(), "src", "app", "articles", "[slug]", "page.tsx"),
  "utf8"
);

test("ページの bodyHasFaq 判定は共有の正規表現を使っている", () => {
  // 判定を二重に持つと、片方だけ直したときに
  // 「本文FAQを表示しているのに JSON-LD は article.faqs」というズレが起きる
  assert.ok(
    /const bodyHasFaq = FAQ_HEADING_RE\.test/.test(PAGE),
    "page.tsx が FAQ_HEADING_RE を使っていない（判定が二重定義になっている）"
  );
});

test("FAQPageのJSON-LDは本文由来のFAQを使う", () => {
  assert.ok(
    /faqsForJsonLd\.length > 0/.test(PAGE) &&
      /mainEntity: faqsForJsonLd\.map/.test(PAGE),
    "JSON-LD が faqsForJsonLd を参照していない"
  );
});

test("画面に見えるFAQは faqs のまま（本文と二重表示しない）", () => {
  assert.ok(
    /\{faqs\.length > 0 && \(/.test(PAGE),
    "表示側が faqsForJsonLd を参照すると本文FAQと二重表示になる"
  );
});

// ─── 本番データ ───────────────────────────────────────

const articlesRaw = JSON.parse(
  fs.readFileSync(path.join(process.cwd(), "data", "articles.json"), "utf8")
);
const allArticles: Array<{
  slug: string;
  status: string;
  content: string;
}> = Array.isArray(articlesRaw) ? articlesRaw : articlesRaw.articles;

const bodyFaqArticles = allArticles.filter(
  (a) => a.status === "published" && FAQ_HEADING_RE.test(a.content || "")
);

test("本文にFAQを直書きした公開記事から、1本残らずFAQを取り出せる", () => {
  assert.ok(bodyFaqArticles.length > 0, "対象記事が0本。抽出の検証になっていない");
  const empty = bodyFaqArticles
    .filter((a) => extractFaqsFromContent(a.content).length === 0)
    .map((a) => a.slug);
  assert.deepEqual(
    empty,
    [],
    `FAQを取り出せない記事がある（この記事から FAQPage が消える）: ${empty.join(", ")}`
  );
});

test("取り出したQ&Aに構造化データとして壊れたものが無い", () => {
  const broken: string[] = [];
  for (const a of bodyFaqArticles) {
    for (const faq of extractFaqsFromContent(a.content)) {
      if (!faq.question.trim()) broken.push(`${a.slug}: 質問が空`);
      if (!faq.answer.trim()) broken.push(`${a.slug}: 回答が空`);
      if (/^#|\*\*|\{\{/.test(faq.question))
        broken.push(`${a.slug}: 質問に装飾が残っている「${faq.question}」`);
      if (faq.question.length > 200)
        broken.push(`${a.slug}: 質問が長すぎる（${faq.question.length}字）`);
    }
  }
  assert.deepEqual(broken, [], broken.join("\n"));
});
