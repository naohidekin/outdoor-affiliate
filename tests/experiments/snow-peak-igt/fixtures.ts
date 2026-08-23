/**
 * テスト専用データ。**本番データではない。**
 *
 * ここに実在の型番を書いていないのは意図的。公式資料で裏を取れていない
 * 値をテストに置くと、あとで「テストにあるから正しいはず」と本番へ
 * 流れる事故が起きる。IDは全て `fixture-` 前置きにしてあり、
 * production-data.test.ts が本番への混入を検出する。
 */

import type { ProductRecord, SourceRecord } from "../../../src/lib/experiments/snow-peak-igt/core.ts";

export const FIXTURE_ID_PREFIX = "fixture-";

export const fixtureSources: SourceRecord[] = [
  {
    id: "fixture-src-official-page",
    publisher: "Fixture Manufacturer",
    title: "Fixture product page",
    url: "https://example.invalid/fixture/product",
    sourceType: "official_product_page",
    lastVerifiedAt: "2026-08-23",
  },
  {
    id: "fixture-src-official-manual",
    publisher: "Fixture Manufacturer",
    title: "Fixture manual",
    url: "https://example.invalid/fixture/manual.pdf",
    sourceType: "official_manual",
    lastVerifiedAt: "2026-08-23",
  },
];

function base(): Omit<ProductRecord, "id" | "productName" | "status"> {
  return {
    aliases: [],
    japaneseModelNumber: null,
    usModelNumber: null,
    confirmedSuccessorId: null,
    compatibility: [],
    sourceIds: ["fixture-src-official-page"],
    lastVerifiedAt: "2026-08-23",
    purchaseOptions: [],
  };
}

/** 現行品。日米で型番が違い、aliasも持つ */
export const fixtureCurrent: ProductRecord = {
  ...base(),
  id: "fixture-current-table",
  productName: "Fixture Alpha Table",
  aliases: ["Alpha Table", "FX-ALPHA"],
  japaneseModelNumber: "FX-100",
  usModelNumber: "FXU-100",
  status: "current",
  purchaseOptions: [
    {
      market: "us",
      merchant: "Fixture Store",
      url: "https://example.invalid/fixture/buy",
      affiliate: true,
    },
  ],
};

/** 廃番だが後継品が特定できている */
export const fixtureDiscontinuedWithSuccessor: ProductRecord = {
  ...base(),
  id: "fixture-discontinued-with-successor",
  productName: "Fixture Beta Table",
  japaneseModelNumber: "FX-200",
  usModelNumber: "FXU-200",
  status: "discontinued",
  confirmedSuccessorId: "fixture-current-table",
  // 後継品があっても互換性は別概念。confirmed には出典を付ける
  compatibility: [
    {
      targetId: "fixture-current-table",
      status: "confirmed",
      sourceIds: ["fixture-src-official-manual"],
      notes: "Fixture note.",
    },
  ],
};

/** 廃番で後継品なし */
export const fixtureDiscontinuedNoSuccessor: ProductRecord = {
  ...base(),
  id: "fixture-discontinued-no-successor",
  productName: "Fixture Gamma Table",
  japaneseModelNumber: "FX-300",
  status: "discontinued",
};

/** 情報が足りない。互換性も未確認 */
export const fixtureUnknown: ProductRecord = {
  ...base(),
  id: "fixture-unknown",
  productName: "Fixture Delta Table",
  japaneseModelNumber: "FX-400",
  status: "unknown",
  compatibility: [
    {
      targetId: "fixture-current-table",
      status: "not_confirmed",
      sourceIds: [],
    },
  ],
};

export const fixtureProducts: ProductRecord[] = [
  fixtureCurrent,
  fixtureDiscontinuedWithSuccessor,
  fixtureDiscontinuedNoSuccessor,
  fixtureUnknown,
];
