// 医師アドバイス未登録のまま公開されている既存記事。
// 2026-08-26 時点で 29 本。新規記事は medical-review-gate が公開を止めるが、
// 既存を一斉に止めるとパイプラインが詰まるため、ここに挙げたものだけ猶予する。
//
// このリストは減らすためのもので、増やすためのものではない。
// 医師アドバイスを書いたら、この行を消すこと。
// tests/medical-review-gate.test.ts がリストの増加を検出する。

export const GRANDFATHERED_WITHOUT_MEDICAL_ADVICE = new Set([
  "winter-sleeping-bag-ranking", // 一酸化炭素・やけど・低体温
  "autumn-camp-complete-guide", // 一酸化炭素・低体温
  "autumn-winter-camp-cold-gear-guide", // 一酸化炭素・低体温
  "landnest-shelter-vs-2room-comparison", // 一酸化炭素・熱中症
  "neck-cooler-ranking", // やけど・熱中症
  "single-burner-ranking", // 一酸化炭素・やけど
  "summer-camp-heat-gear-guide", // 熱中症・虫よけ成分
  "winter-camp-beginners-checklist", // 一酸化炭素・低体温
  "autumn-camp-clothing-layering-guide", // 低体温
  "budget-sleeping-bag-ranking", // 低体温
  "camping-beginner-gear-checklist", // 一酸化炭素
  "family-tent-ranking", // 一酸化炭素
  "fire-blower-ranking", // 一酸化炭素
  "firepit-beginner-guide", // やけど
  "gas-lantern-ranking", // 一酸化炭素
  "growler-comparison-summer-ice", // やけど
  "gw-camp-checklist-2026", // 虫よけ成分
  "kids-sleeping-bag-ranking", // 一酸化炭素
  "landlock-vs-landnest-shelter", // 一酸化炭素
  "led-lantern-ranking", // 一酸化炭素
  "led-tent-light-ranking", // 一酸化炭素
  "portable-cooler-fan-guide", // 一酸化炭素
  "portable-power-station-guide", // 一酸化炭素
  "rain-camp-gear-essentials", // 低体温
  "rainwear-ranking", // 低体温
  "snow-peak-landlock-x-review", // 一酸化炭素
  "spring-sleeping-bag-guide", // 低体温
  "stanley-water-jug-review", // 熱中症
  "summer-family-tent-ranking", // 熱中症
]);
