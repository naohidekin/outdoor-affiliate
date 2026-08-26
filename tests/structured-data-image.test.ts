import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { sizedImageUrl } from "../src/lib/imageSize.ts";

// 構造化データの image が小さいままだと、Googleは画像付きリッチリザルトの
// 対象から外す。表示側は sizedImageUrl でその都度サイズを指定し直していたが、
// JSON-LD だけが products.json の生URLを使っていて、保存されている
// ?_ex=128x128 がそのまま構造化データに出ていた。

test("楽天サムネイルの小さいサイズ指定が1200pxに置き換わる", () => {
  const stored =
    "https://thumbnail.image.rakuten.co.jp/@0_mall/corona-official/cabinet/10727571/imgrc0118802882.jpg?_ex=128x128";
  const out = sizedImageUrl(stored, 1200);
  assert.ok(out.includes("_ex=1200x1200"), out);
  assert.ok(!out.includes("128x128"), `小さい指定が残っている: ${out}`);
});

test("_ex=600x600 も1200pxに引き上がる", () => {
  const out = sizedImageUrl(
    "https://thumbnail.image.rakuten.co.jp/@0_mall/shop/cabinet/a.jpg?_ex=600x600",
    1200
  );
  assert.ok(out.includes("_ex=1200x1200"), out);
});

test("Amazonの画像もサイズ修飾子が付く", () => {
  const out = sizedImageUrl(
    "https://m.media-amazon.com/images/I/71abcdefg._AC_SL300_.jpg",
    1200
  );
  assert.ok(out.includes("_AC_SL1200_"), out);
});

test("メーカー公式など仕様不明のホストは原URLのまま", () => {
  const url = "https://img.snowpeak.co.jp/item/SDE-001RH.jpg";
  assert.equal(sizedImageUrl(url, 1200), url);
});

test("空文字はそのまま返る（フォールバックの || が効くこと）", () => {
  assert.equal(sizedImageUrl("", 1200), "");
  assert.equal(sizedImageUrl("", 1200) || "fallback", "fallback");
});

// ─── ページ側の結線 ───────────────────────────────────

const PAGE = fs.readFileSync(
  path.join(process.cwd(), "src", "app", "articles", "[slug]", "page.tsx"),
  "utf8"
);

test("Article の image は sizedImageUrl を通している", () => {
  assert.ok(
    /image:\s*\n?\s*sizedImageUrl\(/.test(PAGE),
    "Article の image が生URLに戻っている"
  );
});

test("Product の image も sizedImageUrl を通している", () => {
  assert.ok(
    /image: p\.imageUrl \? sizedImageUrl\(p\.imageUrl, 1200\) : undefined/.test(
      PAGE
    ),
    "Product の image が生URLに戻っている"
  );
});

test("画像が無いときは動的生成のOGP画像にフォールバックする", () => {
  assert.ok(
    /\|\| `\$\{baseUrl\}\/articles\/\$\{article\.slug\}\/opengraph-image`/.test(
      PAGE
    ),
    "フォールバックが外れている"
  );
});

// ─── 本番データ ───────────────────────────────────────

const productsRaw = JSON.parse(
  fs.readFileSync(path.join(process.cwd(), "data", "products.json"), "utf8")
);
const products: Array<{ id: string; imageUrl?: string }> = Array.isArray(
  productsRaw
)
  ? productsRaw
  : productsRaw.products;

test("本番の全画像URLが1200px指定に変換できる（小さい指定が残らない）", () => {
  const stuck: string[] = [];
  for (const p of products) {
    if (!p.imageUrl) continue;
    const out = sizedImageUrl(p.imageUrl, 1200);
    const small = out.match(/_ex=(\d+)x\d+/);
    if (small && Number(small[1]) < 1200) stuck.push(`${p.id}: ${out}`);
    const amz = out.match(/_AC_SL(\d+)_/);
    if (amz && Number(amz[1]) < 1200) stuck.push(`${p.id}: ${out}`);
  }
  assert.deepEqual(stuck, [], stuck.join("\n"));
});
