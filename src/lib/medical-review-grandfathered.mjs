// 医師アドバイス未登録のまま公開されている既存記事。
// 2026-08-28 時点で 0 本。新規記事は medical-review-gate が公開を止めるが、
// 既存を一斉に止めるとパイプラインが詰まるため、ここに挙げたものだけ猶予する。
//
// このリストは減らすためのもので、増やすためのものではない。
// 医師アドバイスを書いたら、この行を消すこと。
// tests/medical-review-gate.test.ts がリストの増加を検出する。

export const GRANDFATHERED_WITHOUT_MEDICAL_ADVICE = new Set([
]);
