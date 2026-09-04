import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";

// 商品データは楽天の検索結果から自動で取り込まれる経路があり、出品者が
// つけた販促文言がそのまま name に入ることがある。記事に載ると読者には
// 「★クーポンで3938円★即納★ 折りたたみ扇風機」と表示される。
//
// クーポン価格は時間で変わるので、商品名に価格が入っていると記事の表示と
// 実売価格がズレたときに嘘になる。仕様は残して販促文言だけ落とす。

const ROOT = process.cwd();

const productsRaw = JSON.parse(
  fs.readFileSync(path.join(ROOT, "data", "products.json"), "utf8")
);
const products: Array<{
  id: string;
  name: string;
  brand?: string;
  price?: number;
  imageUrl?: string;
  affiliateUrl?: string;
}> = Array.isArray(productsRaw) ? productsRaw : productsRaw.products;

const articlesRaw = JSON.parse(
  fs.readFileSync(path.join(ROOT, "data", "articles.json"), "utf8")
);
const articles: Array<{
  slug: string;
  status: string;
  content: string;
  productIds?: string[];
}> = Array.isArray(articlesRaw) ? articlesRaw : articlesRaw.articles;

/** 公開記事に実際に載る商品ID。下書きは対象外にする */
const publishedProductIds = new Set<string>();
for (const a of articles) {
  if (a.status !== "published") continue;
  for (const id of a.productIds ?? []) publishedProductIds.add(id);
  for (const m of (a.content ?? "").matchAll(
    /\{\{(?:product|comparison|ranking):([a-z0-9,\-]+)\}\}/g
  )) {
    for (const id of m[1].split(",")) publishedProductIds.add(id);
  }
}

const onPublished = products.filter((p) => publishedProductIds.has(p.id));

test("公開記事に載る商品が1件以上ある（検証が空振りしていない）", () => {
  assert.ok(onPublished.length > 50, `対象が ${onPublished.length} 件しかない`);
});

test("公開記事に載る商品名に販促文言が入っていない", () => {
  const PROMO = [
    /★/,
    /クーポン/,
    /即納/,
    /在庫有/,
    /半額/,
    /タイムセール/,
    /ポイント\d+倍/,
    /送料無料/,
    /^【\s*\d+%OFF/,
  ];
  const bad: string[] = [];
  for (const p of onPublished) {
    for (const re of PROMO) {
      if (re.test(p.name ?? "")) {
        bad.push(`${p.id}: 「${(p.name ?? "").slice(0, 50)}」`);
        break;
      }
    }
  }
  assert.deepEqual(bad, [], bad.join("\n"));
});

test("公開記事に載る商品名に価格が埋め込まれていない", () => {
  // 「クーポンで3938円」のように名前に価格が入ると、実売価格が変わった
  // ときに記事が嘘をつく。価格は price フィールドが持つ
  const bad: string[] = [];
  for (const p of onPublished) {
    // 利用券・ふるさと納税の返礼品は券面額が商品名の一部。
    // 「クーポンで3938円」とは別物なので対象外にする
    if (/利用券|ふるさと納税|商品券|ギフト券/.test(p.name ?? "")) continue;
    if (/\d{3,6}\s*円/.test(p.name ?? ""))
      bad.push(`${p.id}: 「${(p.name ?? "").slice(0, 50)}」`);
  }
  assert.deepEqual(bad, [], bad.join("\n"));
});

test("公開記事に載る商品名が長すぎない", () => {
  // 楽天の商品名はキーワードを詰め込んだ100字超のものがあり、
  // カードや比較表のレイアウトが崩れる
  const bad: string[] = [];
  for (const p of onPublished) {
    if ((p.name ?? "").length > 90)
      bad.push(`${p.id}: ${(p.name ?? "").length}字`);
  }
  assert.deepEqual(bad, [], bad.join("\n"));
});

// 画像が無いまま公開記事に載っている商品。2026-08-28 時点で4件あり、
// すべて安全系の記事に出るものだった（COチェッカー、やけど用
// ドレッシング材、熱中症グッズ2点）。医師名で安全を語る記事で商品画像が
// 欠けているのは説得力に直結する。楽天API復旧後に埋める。
// このリストは減らすためのもの。新しく増えたらテストが落ちる。
const KNOWN_MISSING_IMAGE = new Set([
  "co-detector-dod-cg1559",
  "first-aid-burn-aid",
  "heatstroke-cooling-towel",
  "heatstroke-neck-cooler-kids",
]);

test("公開記事に載る商品の画像欠落が増えていない", () => {
  const noImage = onPublished.filter((p) => !p.imageUrl).map((p) => p.id);
  const added = noImage.filter((id) => !KNOWN_MISSING_IMAGE.has(id));
  assert.deepEqual(
    added,
    [],
    `画像の無い掲載商品が増えました: ${added.join(", ")}`
  );
  const fixed = [...KNOWN_MISSING_IMAGE].filter((id) => !noImage.includes(id));
  if (fixed.length > 0) {
    console.log(
      `  [注意] 画像が付いたので KNOWN_MISSING_IMAGE から消せます: ${fixed.join(", ")}`
    );
  }
});

test("公開記事に載る商品に、購入リンクか入手方法のどちらかがある", () => {
  // ProductCard は「どの販路にもリンクが無い商品（メーカー公式限定の
  // 抽選販売品など）」に specs の「入手方法」を表示する作りになっている。
  // コロナ OUTFIELD BREEZE BOX がまさにそれで、リンクが無いのは意図的。
  // 当初この検査はリンクだけを見ていて、正しく扱われている商品まで
  // 違反として拾った。コード側の仕様に合わせる。
  //
  // 逆に、リンクも入手方法も無いと、比較表の「購入する」欄が空のまま
  // 出る。読者から見ると買い方が分からない
  const orphan = onPublished
    .filter((p) => {
      const withLink =
        p.affiliateUrl ||
        (p as { amazonUrl?: string }).amazonUrl ||
        (p as { yahooUrl?: string }).yahooUrl;
      const howToGet = (p as { specs?: Record<string, string> }).specs?.[
        "入手方法"
      ];
      return !withLink && !howToGet;
    })
    .map((p) => p.id);
  assert.deepEqual(
    orphan,
    [],
    `購入リンクも入手方法も無い掲載商品: ${orphan.join(", ")}。` +
      `アフィリエイトURLを入れるか、specs に「入手方法」を追加してください`
  );
});

/**
 * 2026-08-30 に管理画面（Supabase）から削除した重複商品。
 * `db:sync` は upsert なので、**ローカルのJSONに残っていると次の同期で
 * 復活する**。実際に削除直後の products.json には6件とも残っていた。
 * 管理画面での削除とJSONからの削除は別作業で、片方だけやると戻る。
 */
const DELETED_DUPLICATES = [
  "rakuten-i-collect-10010577",
  "chair-006",
  "firepit-picogrill-398",
  "kettle-uniflame-yama900",
  "peg-hammer-snowpeak-proc-review",
  "sb-kids-003",
  // 2026-09-02 追加。tent-002 と Amazon の ASIN が同一（B0DFG51JMQ）だった。
  // アメニティドームS の価格 ¥44,000 と室内高 120cm が汚染された出どころ
  "tent-sp-amenity-dome-m",
];

/** 各ペアで残したほう。消し間違いを検出する */
const KEPT_COUNTERPARTS = [
  "burner-s-009",
  "insect-repellent-001",
  "fp-001",
  "uniflame-yama-kettle-900",
  "peg-hammer-snowpeak-proc",
  "sb-budget-002",
  "tent-002",
];

test("管理画面で削除した重複商品がJSONに残っていない", () => {
  const ids = new Set(products.map((p) => p.id));
  const revived = DELETED_DUPLICATES.filter((id) => ids.has(id));
  assert.deepEqual(
    revived,
    [],
    `管理画面から削除済みの商品が products.json に残っています: ${revived.join(", ")}。` +
      `このまま db:sync すると Supabase に復活します`
  );
});

test("重複ペアで残したほうが消えていない", () => {
  // 名前・価格・ブランドが同一のペアがあり、逆を消す事故が起こりうる。
  // 残すほうは公開記事から参照されている
  const ids = new Set(products.map((p) => p.id));
  const lost = KEPT_COUNTERPARTS.filter((id) => !ids.has(id));
  assert.deepEqual(lost, [], `残すはずの商品が消えています: ${lost.join(", ")}`);
});

test("重複の調査結果が記録されている", () => {
  const p = path.join(ROOT, "docs", "product-duplicates-2026-08-28.md");
  assert.ok(fs.existsSync(p), "docs/product-duplicates-2026-08-28.md が無い");
  const doc = fs.readFileSync(p, "utf8");
  // どれを消したかが読める状態を保つ。再発時の突き合わせに要る
  for (const id of DELETED_DUPLICATES) {
    assert.ok(doc.includes(id), `削除した ${id} が記録から消えている`);
  }
});
