import test from "node:test";
import assert from "node:assert/strict";
import { PEG_GUIDE_SLUG, PEG_SELECTOR_MARKER, publicPegVariants, splitPegGuide, filterPegVariants, pegFilterOptions } from "../src/lib/pegs/selector.ts";
import { PEG_VARIANTS } from "../src/lib/pegs/variants.ts";

const variants = publicPegVariants(PEG_VARIANTS);
const all = { sizeLabel: "", color: "", type: "" };

test("public dataset has exactly the 17 documented combinations and no private/image/offer fields", () => {
  assert.equal(PEG_GUIDE_SLUG, "tent-pegs-ground-material-guide");
  assert.equal(variants.length, 17);
  assert.equal(new Set(variants.map((variant) => variant.id)).size, 17);
  assert.equal(variants.filter((variant) => variant.id.startsWith("snowpeak-")).length, 4);
  assert.equal(variants.filter((variant) => variant.id.startsWith("ellisse-")).length, 11);
  assert.equal(variants.filter((variant) => variant.id.startsWith("msr-")).length, 2);
  assert.doesNotMatch(JSON.stringify(PEG_VARIANTS), /imageUrl|imageRights|sourceImage|price|availability|Slack|thread|publication_review|approved/i);
  assert.deepEqual(publicPegVariants([{ ...PEG_VARIANTS[0], imageUrl: "https://private.test/image.png", approval: "private", slackThread: "private", price: 0 }]), [variants[0]]);
});

test("marker split preserves the article and fails closed on missing or duplicate selector", () => {
  assert.deepEqual(splitPegGuide(`before\n${PEG_SELECTOR_MARKER}\nafter`), ["before\n", "\nafter"]);
  assert.throws(() => splitPegGuide("no marker"));
  assert.throws(() => splitPegGuide(`${PEG_SELECTOR_MARKER}${PEG_SELECTOR_MARKER}`));
});

test("filters intersect existing combinations without generating nonexistent colors/sizes", () => {
  assert.equal(filterPegVariants(variants, all).length, 17);
  assert.equal(filterPegVariants(variants, { ...all, sizeLabel: "18cm" }).length, 5);
  assert.equal(filterPegVariants(variants, { ...all, sizeLabel: "18cm", color: "ブラック" }).length, 0);
  assert.deepEqual(filterPegVariants(variants, { ...all, sizeLabel: "28cm", color: "ブラック" }).map((variant) => variant.id), ["ellisse-28-black"]);
  assert.equal(filterPegVariants(variants, { ...all, color: "レッド", type: "砂・雪向けの幅広アルミペグ" }).length, 1);
  assert.equal(filterPegVariants(variants, { ...all, sizeLabel: "不明" }).length, 0);
  assert.deepEqual(pegFilterOptions(variants, "sizeLabel"), ["18cm", "19cm", "20cm", "24cm", "28cm", "30cm", "38cm", "40cm", "50cm"]);
});

test("purchase links preserve exact destination, pack counts and seller selection disclosure", () => {
  const links = variants.flatMap((variant) => variant.purchaseLinks);
  assert.equal(links.length, 15);
  assert.equal(links.filter((link) => link.kind === "select_at_destination").length, 14);
  const exact = links.filter((link) => link.kind === "exact_variant");
  assert.equal(exact.length, 1);
  assert.equal(exact[0].manufacturerModel, "MK-280K");
  assert.equal(exact[0].packCount, 8);
  for (const link of links) {
    assert.equal(new URL(link.url).searchParams.get("pc"), link.destinationUrl);
    if (link.kind === "select_at_destination") assert.match(link.note, /選択.*引き継がれません/);
  }
  assert.ok(variants.filter((variant) => variant.id.startsWith("msr-")).every((variant) => variant.purchaseLinks.length === 0));
  for (const variant of variants) {
    assert.equal(new URL(variant.amazonSearchUrl).pathname, "/s");
    assert.equal(new URL(variant.amazonSearchUrl).searchParams.get("tag"), "camp78-22");
  }
  assert.ok(variants.filter((variant) => variant.sizeLabel === "18cm").every((variant) => variant.lengthMm === null && variant.note.includes("184mm")));
});

test("unsafe, rewritten and duplicate destination URLs are rejected", () => {
  for (const manufacturerUrl of ["javascript:alert(1)", "https://ec.snowpeak.co.jp.evil.test/a", "https://user@ec.snowpeak.co.jp/a", "http://ec.snowpeak.co.jp/a", "https://ec.snowpeak.co.jp:8443/a"]) {
    assert.throws(() => publicPegVariants([{ ...PEG_VARIANTS[0], manufacturerUrl }]));
  }
  for (const amazonSearchUrl of ["https://www.amazon.co.jp/dp/B000000001?tag=camp78-22", "https://www.amazon.co.jp/s?k=peg&tag=wrong-22", "https://www.amazon.co.jp/s?k=peg&tag=camp78-22&tag=wrong-22"]) {
    assert.throws(() => publicPegVariants([{ ...PEG_VARIANTS[0], amazonSearchUrl }]));
  }
  const link = PEG_VARIANTS[0].purchaseLinks[0];
  for (const patch of [{ destinationUrl: "https://item.rakuten.co.jp/other/item/" }, { url: link.url + "&pc=https://evil.test" }, { packCount: 1.5 }, { kind: "unknown" }]) {
    assert.throws(() => publicPegVariants([{ ...PEG_VARIANTS[0], purchaseLinks: [{ ...link, ...patch }] }]));
  }
  assert.throws(() => publicPegVariants([PEG_VARIANTS[0], PEG_VARIANTS[0]]));
});
