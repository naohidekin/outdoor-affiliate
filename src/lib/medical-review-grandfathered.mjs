// 医師アドバイス未登録のまま公開されている既存記事。
// 2026-08-28 時点で 11 本。新規記事は medical-review-gate が公開を止めるが、
// 既存を一斉に止めるとパイプラインが詰まるため、ここに挙げたものだけ猶予する。
//
// このリストは減らすためのもので、増やすためのものではない。
// 医師アドバイスを書いたら、この行を消すこと。
// tests/medical-review-gate.test.ts がリストの増加を検出する。

export const GRANDFATHERED_WITHOUT_MEDICAL_ADVICE = new Set([
  "landnest-shelter-vs-2room-comparison", // 一酸化炭素・熱中症
  "camping-beginner-gear-checklist", // 一酸化炭素
  "family-tent-ranking", // 一酸化炭素
  "fire-blower-ranking", // 一酸化炭素
  "gas-lantern-ranking", // 一酸化炭素
  "landlock-vs-landnest-shelter", // 一酸化炭素
  "led-lantern-ranking", // 一酸化炭素
  "led-tent-light-ranking", // 一酸化炭素
  "portable-cooler-fan-guide", // 一酸化炭素
  "portable-power-station-guide", // 一酸化炭素
  "snow-peak-landlock-x-review", // 一酸化炭素
]);
