import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import {
  EN_LANG,
  EN_PAGES,
  enAbsoluteUrl,
  enCanonical,
  enSitemapEntries,
  finderRobots,
  hasSearchQuery,
} from "../../../src/lib/experiments/snow-peak-igt/seo.ts";

const ROOT = process.cwd();
const read = (p: string) => fs.readFileSync(path.join(ROOT, p), "utf8");

const PAGE_FILES: Record<string, string> = {
  "/en": "src/app/en/page.tsx",
  "/en/tools/snow-peak-igt-model-finder":
    "src/app/en/tools/snow-peak-igt-model-finder/page.tsx",
  "/en/guides/snow-peak-igt-model-numbers":
    "src/app/en/guides/snow-peak-igt-model-numbers/page.tsx",
  "/en/methodology": "src/app/en/methodology/page.tsx",
  "/en/affiliate-disclosure": "src/app/en/affiliate-disclosure/page.tsx",
};

// ─── URL ──────────────────────────────────────────────

test("実装対象の5URLがすべて定義されている", () => {
  const paths = EN_PAGES.map((p) => p.path).sort();
  assert.deepEqual(paths, Object.keys(PAGE_FILES).sort());
});

test("英語ページのファイルが実在する", () => {
  for (const [route, file] of Object.entries(PAGE_FILES)) {
    assert.ok(fs.existsSync(path.join(ROOT, file)), `${route} のページが無い`);
  }
});

// ─── canonical ────────────────────────────────────────

test("canonical は自己参照（自分のパスを指す）", () => {
  for (const page of EN_PAGES) {
    assert.equal(enCanonical(page.path), page.path);
  }
});

test("各英語ページが canonical を設定している", () => {
  for (const [route, file] of Object.entries(PAGE_FILES)) {
    const src = read(file);
    assert.ok(
      src.includes("alternates: { canonical: enCanonical("),
      `${route} が canonical を設定していない`
    );
    assert.ok(src.includes(`enCanonical("${route}")`), `${route} の canonical が自己参照でない`);
  }
});

test("絶対URLは本番オリジンを指す", () => {
  assert.equal(enAbsoluteUrl("/en"), "https://camp-gear-lab.com/en");
});

// ─── lang ─────────────────────────────────────────────

test("英語セクションの言語タグは en-US", () => {
  assert.equal(EN_LANG, "en-US");
});

test("英語レイアウトが lang を設定している", () => {
  const src = read("src/app/en/layout.tsx");
  assert.ok(src.includes("lang={EN_LANG}"), "レイアウトのラッパーに lang が無い");
});

test("英語ページの OpenGraph locale が en_US", () => {
  for (const [route, file] of Object.entries(PAGE_FILES)) {
    assert.ok(read(file).includes('locale: "en_US"'), `${route} の og:locale が en_US でない`);
  }
});

// ─── sitemap ──────────────────────────────────────────

test("sitemap に英語5URLが載る", () => {
  const entries = enSitemapEntries(new Date("2026-08-23T00:00:00Z"));
  const urls = entries.map((e) => e.url).sort();
  assert.deepEqual(
    urls,
    Object.keys(PAGE_FILES)
      .map((p) => `https://camp-gear-lab.com${p}`)
      .sort()
  );
});

test("sitemap.ts が英語エントリを実際に連結している", () => {
  const src = read("src/app/sitemap.ts");
  assert.ok(src.includes("enSitemapEntries"), "sitemap.ts が英語エントリを呼んでいない");
  assert.ok(
    src.includes("...englishPages"),
    "sitemap.ts が英語エントリを返り値に含めていない"
  );
});

test("sitemap のURLにクエリ文字列が含まれない", () => {
  for (const e of enSitemapEntries(new Date())) {
    assert.ok(!e.url.includes("?"), `クエリ付きURLが sitemap に載っている: ${e.url}`);
  }
});

// ─── hreflang ─────────────────────────────────────────

test("存在しない hreflang 対応先を生成しない", () => {
  const files = [...Object.values(PAGE_FILES), "src/app/en/layout.tsx", "src/components/en/EnChrome.tsx"];
  for (const file of files) {
    const src = read(file);
    // metadata の alternates.languages（＝hreflang注釈）を作らない
    assert.ok(!/languages\s*:/.test(src), `${file} が alternates.languages を設定している`);
    // 属性としての hrefLang だけを見る。コメント中の「hreflang」という
    // 語まで拾うと、方針を説明したコメントで落ちる
    assert.ok(!/hrefLang\s*=/.test(src), `${file} に hrefLang 属性が残っている`);
  }
});

test("英語セクションの sitemap エントリに alternates が付かない", () => {
  for (const e of enSitemapEntries(new Date())) {
    assert.equal(
      (e as { alternates?: unknown }).alternates,
      undefined,
      "sitemap エントリに hreflang alternates が付いている"
    );
  }
});

// ─── 検索結果を index させない ────────────────────────

test("クエリ無しの Finder は index させる", () => {
  assert.deepEqual(finderRobots(false), { index: true, follow: true });
});

test("クエリ付きの Finder は noindex", () => {
  assert.deepEqual(finderRobots(true), { index: false, follow: true });
});

test("hasSearchQuery が文字列・配列・空を正しく判定する", () => {
  assert.equal(hasSearchQuery({ q: "CK-080" }), true);
  assert.equal(hasSearchQuery({ q: ["CK-080"] }), true);
  assert.equal(hasSearchQuery({ q: "" }), false);
  assert.equal(hasSearchQuery({ q: "   " }), false);
  assert.equal(hasSearchQuery({}), false);
  assert.equal(hasSearchQuery(undefined), false);
});

test("Finder ページが searchParams から robots を決めている", () => {
  const src = read(PAGE_FILES["/en/tools/snow-peak-igt-model-finder"]);
  assert.ok(src.includes("finderRobots(hasSearchQuery("), "robots がクエリ依存になっていない");
});

test("型番ごとの indexable URL を生成しない（動的セグメントが無い）", () => {
  const walk = (dir: string): string[] => {
    const full = path.join(ROOT, dir);
    if (!fs.existsSync(full)) return [];
    return fs.readdirSync(full, { withFileTypes: true }).flatMap((e) =>
      e.isDirectory() ? [path.join(dir, e.name), ...walk(path.join(dir, e.name))] : []
    );
  };
  const dynamic = walk("src/app/en").filter((d) => path.basename(d).includes("["));
  assert.deepEqual(dynamic, [], `英語セクションに動的セグメントがある: ${dynamic.join(", ")}`);
});

test("Finder は検索のたびにURLを書き換えない", () => {
  const src = read("src/components/en/ModelFinder.tsx");
  for (const forbidden of ["router.push", "router.replace", "pushState", "useSearchParams"]) {
    assert.ok(!src.includes(forbidden), `ModelFinder が ${forbidden} を使っている`);
  }
});

test("generateStaticParams で商品ページを量産していない", () => {
  for (const file of Object.values(PAGE_FILES)) {
    assert.ok(
      !read(file).includes("generateStaticParams"),
      `${file} が generateStaticParams を使っている`
    );
  }
});
