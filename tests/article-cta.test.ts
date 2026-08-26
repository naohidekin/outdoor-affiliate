import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { showTopCta } from "../src/lib/articleCta.ts";

test("安全・医学系の記事は冒頭に購入ボタンを出さない", () => {
  for (const slug of [
    "family-camp-safety-guide",
    "kids-camp-first-aid-kit",
    "kids-camp-heatstroke-prevention",
  ]) {
    assert.equal(showTopCta(slug), false, `${slug} で冒頭CTAが出ている`);
  }
});

test("記事と冒頭CTAの中身がズレる記事も除外されている", () => {
  // 電気毛布の記事に紐づく商品がポータブル電源3点だけになったため、
  // 「迷ったらこの3つ」が6〜10万円のポータブル電源になっていた。
  // 5,000円の電気毛布を探しに来た読者には推奨の電気毛布に見える
  assert.equal(showTopCta("camp-electric-blanket-guide"), false);
});

test("通常のランキング・比較記事では冒頭CTAを出す", () => {
  for (const slug of [
    "portable-cooler-fan-guide",
    "winter-camp-heating-comparison",
    "gas-lantern-ranking",
    "kids-sleeping-bag-ranking",
  ]) {
    assert.equal(showTopCta(slug), true, `${slug} で冒頭CTAが消えている`);
  }
});

test("除外リストは実在する記事だけを指している", () => {
  // slugを打ち間違えても何も起きないので、静かに効かないまま残りやすい
  const raw = JSON.parse(
    fs.readFileSync(path.join(process.cwd(), "data", "articles.json"), "utf8")
  );
  const all: Array<{ slug: string }> = Array.isArray(raw) ? raw : raw.articles;
  const slugs = new Set(all.map((a) => a.slug));

  const src = fs.readFileSync(
    path.join(process.cwd(), "src", "lib", "articleCta.ts"),
    "utf8"
  );
  const listed = [...src.matchAll(/^\s*"([a-z0-9-]+)",/gm)].map((m) => m[1]);
  assert.ok(listed.length >= 4, `除外リストが読み取れていない: ${listed.length}件`);

  const missing = listed.filter((s) => !slugs.has(s));
  assert.deepEqual(missing, [], `存在しない記事を指している: ${missing.join(", ")}`);
});
