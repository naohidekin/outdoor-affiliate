import test from "node:test";
import assert from "node:assert/strict";
import {
  EVIDENCE_STATEMENTS,
  PRODUCT_STATUS_LABEL,
  UNKNOWN_LABEL,
  compatibilityStatement,
  displayOrUnknown,
  normalizeModelNumber,
  normalizeName,
  searchProducts,
  successorStatement,
} from "../../../src/lib/experiments/snow-peak-igt/core.ts";
import {
  fixtureCurrent,
  fixtureDiscontinuedNoSuccessor,
  fixtureDiscontinuedWithSuccessor,
  fixtureProducts,
  fixtureUnknown,
} from "./fixtures.ts";

function idsFor(query: string): string[] {
  const r = searchProducts(query, fixtureProducts);
  return r.status === "found" ? r.matches.map((m) => m.product.id) : [];
}

// ─── 正規化 ───────────────────────────────────────────

test("型番の正規化: 大文字小文字・ハイフン・空白・全角を吸収する", () => {
  const expected = "FX100";
  for (const input of [
    "FX-100",
    "fx-100",
    "FX100",
    "fx100",
    "  FX-100  ",
    "FX - 100",
    "FX 100",
    "ＦＸ－１００", // 全角
    "FX_100",
  ]) {
    assert.equal(normalizeModelNumber(input), expected, `failed for ${input}`);
  }
});

test("型番の正規化: null や空文字でも落ちない", () => {
  assert.equal(normalizeModelNumber(null), "");
  assert.equal(normalizeModelNumber(undefined), "");
  assert.equal(normalizeModelNumber("   "), "");
});

test("商品名の正規化: 小文字化し、連続空白を1つに畳む", () => {
  assert.equal(normalizeName("  Fixture   Alpha  Table "), "fixture alpha table");
});

// ─── 検索 ─────────────────────────────────────────────

test("型番の完全一致で引ける（日本型番）", () => {
  assert.deepEqual(idsFor("FX-100"), [fixtureCurrent.id]);
});

test("型番の完全一致で引ける（米国型番）", () => {
  assert.deepEqual(idsFor("FXU-100"), [fixtureCurrent.id]);
});

test("大文字・小文字の違いを吸収する", () => {
  assert.deepEqual(idsFor("fx-100"), [fixtureCurrent.id]);
});

test("ハイフンの有無を吸収する", () => {
  assert.deepEqual(idsFor("FX100"), [fixtureCurrent.id]);
});

test("前後・途中の空白を吸収する", () => {
  assert.deepEqual(idsFor("  FX 100 "), [fixtureCurrent.id]);
});

test("商品名で引ける（部分一致）", () => {
  assert.deepEqual(idsFor("Alpha"), [fixtureCurrent.id]);
});

test("alias で引ける", () => {
  assert.deepEqual(idsFor("FX-ALPHA"), [fixtureCurrent.id]);
});

test("型番は部分一致させない（FX-1000 は FX-100 を掴まない）", () => {
  assert.deepEqual(idsFor("FX-1000"), []);
});

test("見つからないときは not_found を返す", () => {
  const r = searchProducts("NOT-A-MODEL", fixtureProducts);
  assert.equal(r.status, "not_found");
});

test("空の検索語は empty（検索を実行しない）", () => {
  assert.equal(searchProducts("", fixtureProducts).status, "empty");
  assert.equal(searchProducts("   ", fixtureProducts).status, "empty");
});

test("データが空でも落ちず not_found を返す", () => {
  assert.equal(searchProducts("FX-100", []).status, "not_found");
});

// ─── 状態の表示 ───────────────────────────────────────

test("Current / Discontinued / Unknown のラベル", () => {
  assert.equal(PRODUCT_STATUS_LABEL[fixtureCurrent.status], "Current");
  assert.equal(
    PRODUCT_STATUS_LABEL[fixtureDiscontinuedNoSuccessor.status],
    "Discontinued"
  );
  assert.equal(PRODUCT_STATUS_LABEL[fixtureUnknown.status], UNKNOWN_LABEL);
});

test("後継品がある廃番品は Current equivalent identified", () => {
  assert.equal(
    successorStatement(fixtureDiscontinuedWithSuccessor),
    EVIDENCE_STATEMENTS.currentEquivalent
  );
});

test("後継品がない廃番品は Discontinued — no confirmed successor", () => {
  assert.equal(
    successorStatement(fixtureDiscontinuedNoSuccessor),
    EVIDENCE_STATEMENTS.discontinuedNoSuccessor
  );
});

test("状態が unknown なら Insufficient evidence", () => {
  assert.equal(successorStatement(fixtureUnknown), EVIDENCE_STATEMENTS.insufficient);
});

test("互換性は confirmed かつ出典ありのときだけ Confirmed by official documentation", () => {
  const confirmed = fixtureDiscontinuedWithSuccessor.compatibility[0];
  assert.equal(compatibilityStatement(confirmed), EVIDENCE_STATEMENTS.confirmed);

  const notConfirmed = fixtureUnknown.compatibility[0];
  assert.equal(compatibilityStatement(notConfirmed), EVIDENCE_STATEMENTS.insufficient);
});

test("confirmed でも出典が無ければ Insufficient evidence に倒す", () => {
  assert.equal(
    compatibilityStatement({
      targetId: "fixture-current-table",
      status: "confirmed",
      sourceIds: [],
    }),
    EVIDENCE_STATEMENTS.insufficient
  );
});

test("後継品があること自体は互換性の根拠にしない（別項目として持つ）", () => {
  // 後継品はあるが、互換性の判定はあくまで compatibility 側の出典で決まる
  const p = fixtureDiscontinuedWithSuccessor;
  assert.equal(p.confirmedSuccessorId, fixtureCurrent.id);
  assert.equal(
    compatibilityStatement({ targetId: fixtureCurrent.id, status: "unknown", sourceIds: [] }),
    EVIDENCE_STATEMENTS.insufficient
  );
});

// ─── 欠損の表示 ───────────────────────────────────────

test("欠損は空文字や 0 ではなく Unknown", () => {
  assert.equal(displayOrUnknown(null), UNKNOWN_LABEL);
  assert.equal(displayOrUnknown(undefined), UNKNOWN_LABEL);
  assert.equal(displayOrUnknown(""), UNKNOWN_LABEL);
  assert.equal(displayOrUnknown("   "), UNKNOWN_LABEL);
  assert.equal(displayOrUnknown("FX-100"), "FX-100");
});

test("米国型番が無い商品は Unknown と表示される", () => {
  assert.equal(fixtureDiscontinuedNoSuccessor.usModelNumber, null);
  assert.equal(
    displayOrUnknown(fixtureDiscontinuedNoSuccessor.usModelNumber),
    UNKNOWN_LABEL
  );
});
