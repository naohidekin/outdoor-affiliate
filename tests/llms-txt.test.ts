import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";

// llms.txt はAIクローラー向けのサイト索引。載っていない記事は、AIから見ると
// 存在しないのと同じになる。以前はカテゴリごとに上位15本で打ち切っていて、
// tentカテゴリが20本に増えた時点で古い5本が静かに消えていた。件数の上限は
// 「増えたときに気づけない」形の欠落を作るので、置かない。

const ROUTE = fs.readFileSync(
  path.join(process.cwd(), "src", "app", "llms.txt", "route.ts"),
  "utf8"
);

test("カテゴリごとの件数上限が復活していない", () => {
  // 件数上限が戻ると、記事が増えたカテゴリから静かに欠落する。
  // ファイル全体から .slice(0, N) を探すと metaDescription の文字数切り詰め
  // （.slice(0, 90)）まで拾ってしまうので、記事リストを組み立てている式だけを見る
  const decl = ROUTE.match(/const sorted = list[\s\S]*?;/);
  assert.ok(decl, "記事リストの組み立て（const sorted = list ...）が見つからない");
  const cap = decl[0].match(/\.slice\(\s*0\s*,\s*\d+\s*\)/);
  assert.equal(
    cap,
    null,
    `記事一覧に件数上限が入っている: ${cap?.[0]}`
  );
});

test("英語ページが索引に載っている", () => {
  for (const p of [
    "/en/tools/snow-peak-igt-model-finder",
    "/en/guides/snow-peak-igt-model-numbers",
    "/en/methodology",
    "/en/affiliate-disclosure",
  ]) {
    assert.ok(ROUTE.includes(p), `llms.txt に ${p} が無い`);
  }
});

// ─── ビルド出力（あれば） ─────────────────────────────
// next build 後のみ存在する。CIでビルド前に走る場合はスキップする

const BODY = path.join(process.cwd(), ".next", "server", "app", "llms.txt.body");

test("ビルド出力の llms.txt に公開記事が全部載っている", (t) => {
  if (!fs.existsSync(BODY)) {
    t.skip("ビルド出力が無い（next build 後に有効）");
    return;
  }
  const body = fs.readFileSync(BODY, "utf8");
  const raw = JSON.parse(
    fs.readFileSync(path.join(process.cwd(), "data", "articles.json"), "utf8")
  );
  const all: Array<{ slug: string; status: string }> = Array.isArray(raw)
    ? raw
    : raw.articles;
  const missing = all
    .filter((a) => a.status === "published")
    .filter((a) => !body.includes(`/articles/${a.slug}`))
    .map((a) => a.slug);
  assert.deepEqual(missing, [], `llms.txt から漏れている: ${missing.join(", ")}`);
});
