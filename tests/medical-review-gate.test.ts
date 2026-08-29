import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { MEDICAL_ADVICE_MAP } from "../src/lib/medicalAdviceData.ts";
import {
  detectMedicalRisks,
  reviewArticleForPublish,
  readMedicalAdviceSlugs,
  MEDICAL_RISK_TERMS,
} from "../src/lib/medical-review-gate.mjs";
import { GRANDFATHERED_WITHOUT_MEDICAL_ADVICE as GRANDFATHERED } from "../src/lib/medical-review-grandfathered.mjs";

// 記事は自動生成・自動公開される。公開前チェックは長く「文字数2,000字以上」
// 「FAQ2問以上」だけで、医学的な内容は素通りしていた。医師名を信頼の核に
// しているサイトで、これは記事が増えるたびにリスクが積み上がる構造だった。

const ROOT = process.cwd();
const ADVICE_SRC = path.join(ROOT, "src", "lib", "medicalAdviceData.ts");

const articlesRaw = JSON.parse(
  fs.readFileSync(path.join(ROOT, "data", "articles.json"), "utf8")
);
const allArticles: Array<{ slug: string; status: string; content: string }> =
  Array.isArray(articlesRaw) ? articlesRaw : articlesRaw.articles;
const published = allArticles.filter((a) => a.status === "published");

// ─── 検出 ─────────────────────────────────────────────

test("医学リスク語を検出できる", () => {
  assert.deepEqual(detectMedicalRisks("幕内で一酸化炭素がたまります"), [
    "一酸化炭素",
  ]);
  assert.deepEqual(detectMedicalRisks("キャンプ用のテーブルを選ぶ"), []);
  const many = detectMedicalRisks("低温やけどと熱中症、そして乳幼児への配慮");
  assert.ok(many.includes("やけど") && many.includes("熱中症") && many.includes("乳幼児"));
});

// ─── ゲートの判定 ─────────────────────────────────────

const has = (slugs: Set<string>) => (s: string) => slugs.has(s);

test("医学リスクが無い記事は通す", () => {
  const r = reviewArticleForPublish(
    { slug: "camp-table-ranking", content: "テーブルの選び方です。" },
    has(new Set()),
    GRANDFATHERED
  );
  assert.equal(r.ok, true);
});

test("医学リスクがあり医師アドバイスがある記事は通す", () => {
  const r = reviewArticleForPublish(
    { slug: "some-article", content: "一酸化炭素に注意。" },
    has(new Set(["some-article"])),
    GRANDFATHERED
  );
  assert.equal(r.ok, true);
});

test("医学リスクがあり医師アドバイスが無い新規記事は止める", () => {
  const r = reviewArticleForPublish(
    { slug: "brand-new-article-2026", content: "一酸化炭素と低温やけどに注意。" },
    has(new Set()),
    GRANDFATHERED
  );
  assert.equal(r.ok, false);
  assert.ok(r.reason?.includes("medicalAdviceData.ts"), "直し方が示されていない");
  assert.ok(r.risks.includes("一酸化炭素"));
});

test("猶予リストにある既存記事は止めないが、警告は返す", () => {
  const slug = [...GRANDFATHERED][0] as string;
  const article = published.find((a) => a.slug === slug)!;
  const r = reviewArticleForPublish(article, has(new Set()), GRANDFATHERED);
  assert.equal(r.ok, true);
  assert.equal(r.grandfathered, true);
  assert.ok(r.reason?.includes("猶予中"));
});

// ─── 猶予リストの健全性 ───────────────────────────────

test("猶予リストが増えていない（減らすためのリスト）", () => {
  // 新規記事を猶予リストに足して通す、という抜け道を塞ぐ。
  // 記事を書いたら医師アドバイスを書く。リストに足すのではない
  const LIMIT = 11; // 2026-08-28 時点（29→21→11）。増やさない。減らしたらこの数字も下げる
  assert.ok(
    GRANDFATHERED.size <= LIMIT,
    `猶予リストが ${GRANDFATHERED.size} 本に増えています（上限 ${LIMIT}）。` +
      `医師アドバイスを書いて減らしてください`
  );
});

test("猶予リストの記事が実在し、まだ医師アドバイスが無い", () => {
  const stale: string[] = [];
  const bySlug = new Map(allArticles.map((a) => [a.slug, a]));
  for (const slug of GRANDFATHERED) {
    if (!bySlug.has(slug)) stale.push(`${slug}: 記事が存在しない`);
    else if (MEDICAL_ADVICE_MAP[slug])
      stale.push(`${slug}: 医師アドバイスが付いたので猶予リストから消せます`);
  }
  assert.deepEqual(stale, [], stale.join("\n"));
});

test("猶予リストに載っていない公開記事は、すべてゲートを通る", () => {
  const slugs = new Set(Object.keys(MEDICAL_ADVICE_MAP));
  const blocked = published
    .filter((a) => !reviewArticleForPublish(a, has(slugs), GRANDFATHERED).ok)
    .map((a) => a.slug);
  assert.deepEqual(
    blocked,
    [],
    `猶予にも医師アドバイスにも入っていない記事: ${blocked.join(", ")}`
  );
});

// ─── ソース読み取りがズレていないか ───────────────────

test("ソースから読んだslugが、実際の MEDICAL_ADVICE_MAP と一致する", () => {
  // publisher は .mjs なので .ts を import できず、ソースを正規表現で読む。
  // 実装とズレると黙って「登録なし」になり、正しい記事まで公開が止まる
  const fromSource = readMedicalAdviceSlugs(fs, ADVICE_SRC);
  const actual = new Set(Object.keys(MEDICAL_ADVICE_MAP));
  assert.deepEqual(
    [...fromSource].sort(),
    [...actual].sort(),
    "ソース読み取りの正規表現が実装とズレています"
  );
});

// ─── パイプラインへの結線 ─────────────────────────────

test("公開スクリプトがゲートを通している", () => {
  const src = fs.readFileSync(
    path.join(ROOT, "scripts", "article-publisher-agent.js"),
    "utf8"
  );
  assert.ok(/reviewArticleForPublish\(/.test(src), "ゲートを呼んでいない");
  assert.ok(
    /if \(!medical\.ok\) blockers\.push/.test(src),
    "ゲートの結果がブロッキング条件に入っていない（警告止まりになっている）"
  );
});

test("生成スクリプトが医学ガードをプロンプトに入れている", () => {
  const src = fs.readFileSync(
    path.join(ROOT, "scripts", "article-writer-agent.js"),
    "utf8"
  );
  assert.ok(/\$\{loadMedicalGuard\(\)\}/.test(src), "プロンプトに入っていない");
  for (const must of ["断定しない", "機序を書く", "薬機法", "低体温"]) {
    assert.ok(src.includes(must), `医学ガードに「${must}」が無い`);
  }
});

test("リスク語の一覧が空になっていない", () => {
  assert.ok(MEDICAL_RISK_TERMS.length >= 8, "リスク語が削られている");
});
