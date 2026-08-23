import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import {
  validateDataset,
  validateProductRecord,
  validateSourceRecord,
} from "../../../src/lib/experiments/snow-peak-igt/core.ts";
import {
  FIXTURE_ID_PREFIX,
  fixtureCurrent,
  fixtureProducts,
  fixtureSources,
} from "./fixtures.ts";

const DATA_DIR = path.join(process.cwd(), "data", "experiments", "snow-peak-igt");

function readArray(file: string): unknown[] {
  const raw = fs.readFileSync(path.join(DATA_DIR, file), "utf8").trim();
  const parsed = JSON.parse(raw === "" ? "[]" : raw);
  assert.ok(Array.isArray(parsed), `${file} must be a JSON array`);
  return parsed;
}

const productionProducts = readArray("products.json");
const productionSources = readArray("sources.json");

// ─── 本番データ ───────────────────────────────────────

test("本番データは検証を通る", () => {
  const errors = validateDataset(productionProducts, productionSources);
  assert.deepEqual(errors, [], `本番データに問題:\n${errors.join("\n")}`);
});

test("本番データに fixture が混入していない", () => {
  const ids = [
    ...productionProducts.map((p) => (p as { id?: string }).id ?? ""),
    ...productionSources.map((s) => (s as { id?: string }).id ?? ""),
  ];
  const leaked = ids.filter((id) => id.startsWith(FIXTURE_ID_PREFIX));
  assert.deepEqual(leaked, [], `fixture が本番へ混入: ${leaked.join(", ")}`);
});

test("本番データに example.invalid（テスト用ドメイン）が入っていない", () => {
  const blob = JSON.stringify([productionProducts, productionSources]);
  assert.ok(
    !blob.includes("example.invalid"),
    "本番データにテスト用ドメインが含まれている"
  );
});

// ─── 必須項目の拒否 ───────────────────────────────────

const knownSources = new Set(fixtureSources.map((s) => s.id));
const knownProducts = new Set(fixtureProducts.map((p) => p.id));

test("source が無い商品データは拒否される", () => {
  const errors = validateProductRecord(
    { ...fixtureCurrent, sourceIds: [] },
    knownSources,
    knownProducts
  );
  assert.ok(
    errors.some((e) => e.includes("sourceIds is required")),
    `sourceIds のエラーが出ていない: ${errors.join(" / ")}`
  );
});

test("存在しない source を指す商品データは拒否される", () => {
  const errors = validateProductRecord(
    { ...fixtureCurrent, sourceIds: ["no-such-source"] },
    knownSources,
    knownProducts
  );
  assert.ok(errors.some((e) => e.includes("unknown source")));
});

test("lastVerifiedAt が無い商品データは拒否される", () => {
  const errors = validateProductRecord(
    { ...fixtureCurrent, lastVerifiedAt: "" },
    knownSources,
    knownProducts
  );
  assert.ok(
    errors.some((e) => e.includes("lastVerifiedAt is required")),
    `lastVerifiedAt のエラーが出ていない: ${errors.join(" / ")}`
  );
});

test("lastVerifiedAt が日付形式でないものは拒否される", () => {
  const errors = validateProductRecord(
    { ...fixtureCurrent, lastVerifiedAt: "recently" },
    knownSources,
    knownProducts
  );
  assert.ok(errors.some((e) => e.includes("lastVerifiedAt is required")));
});

test("出典なしで confirmed を名乗る互換性は拒否される", () => {
  const errors = validateProductRecord(
    {
      ...fixtureCurrent,
      compatibility: [
        { targetId: "fixture-discontinued-no-successor", status: "confirmed", sourceIds: [] },
      ],
    },
    knownSources,
    knownProducts
  );
  assert.ok(
    errors.some((e) => e.includes('is "confirmed" but has no sourceIds')),
    `confirmed+出典なしが素通りした: ${errors.join(" / ")}`
  );
});

test("実在しない商品を後継品として指すデータは拒否される", () => {
  const errors = validateProductRecord(
    { ...fixtureCurrent, confirmedSuccessorId: "no-such-product" },
    knownSources,
    knownProducts
  );
  assert.ok(errors.some((e) => e.includes("confirmedSuccessorId refers to unknown product")));
});

test("購入リンクが絶対https URLでないものは拒否される", () => {
  const errors = validateProductRecord(
    {
      ...fixtureCurrent,
      purchaseOptions: [
        { market: "us", merchant: "Shop", url: "/relative/path", affiliate: false },
      ],
    },
    knownSources,
    knownProducts
  );
  assert.ok(errors.some((e) => e.includes("must be an absolute https URL")));
});

// ─── 出典レコード ─────────────────────────────────────

test("公式以外の sourceType は拒否される", () => {
  const errors = validateSourceRecord({
    ...fixtureSources[0],
    sourceType: "forum_thread",
  });
  assert.ok(
    errors.some((e) => e.includes("official_")),
    `公式以外の出典種別が通ってしまった: ${errors.join(" / ")}`
  );
});

test("正しい fixture データは検証を通る（検証が厳しすぎないことの確認）", () => {
  const errors = validateDataset(fixtureProducts, fixtureSources);
  assert.deepEqual(errors, [], errors.join("\n"));
});
