// @ts-nocheck
/**
 * X投稿ハッシュタグ戦略
 *
 * type × カテゴリ × 月 で 2〜3個のタグを自動選出する。
 * 共通必須: #キャンプ
 * 季節必須: 月に応じた季節タグ
 */

const SEASONAL_TAG = {
  1: "#冬キャンプ",
  2: "#冬キャンプ",
  3: "#春キャンプ",
  4: "#春キャンプ",
  5: "#GWキャンプ",
  6: "#雨キャンプ",
  7: "#夏キャンプ",
  8: "#夏キャンプ",
  9: "#秋キャンプ",
  10: "#紅葉キャンプ",
  11: "#秋キャンプ",
  12: "#冬キャンプ",
};

const CATEGORY_TAG = {
  tent: "#テント",
  light: "#ランタン",
  "sleeping-bag": "#シュラフ",
  burner: "#バーナー",
  backpack: "#バックパック",
  wear: "#アウトドアウェア",
  shoes: "#トレッキングシューズ",
};

const TYPE_TAG = {
  rakuten_sale: "#楽天マラソン",
  amazon_deal: "#Amazonタイムセール",
  news_comment: "#アウトドアニュース",
  gear_story: "#愛用ギア",
};

/**
 * ハッシュタグを2〜3個提案する
 * @param {{ type?: string, categoryId?: string|null, month?: number }} opts
 * @returns {string[]}
 */
export function suggestHashtags({ type, categoryId, month } = {}) {
  const tags = new Set();

  // 1. 共通必須
  tags.add("#キャンプ");

  // 2. タイプ別
  if (type && TYPE_TAG[type]) tags.add(TYPE_TAG[type]);

  // 3. カテゴリ
  if (categoryId && CATEGORY_TAG[categoryId]) tags.add(CATEGORY_TAG[categoryId]);

  // 4. 季節（埋まっていなければ）
  if (tags.size < 3 && month && SEASONAL_TAG[month]) {
    tags.add(SEASONAL_TAG[month]);
  }

  // 最大3個
  return [...tags].slice(0, 3);
}

/**
 * 文字列としてのスペース区切りで返す
 */
export function suggestHashtagString(opts) {
  return suggestHashtags(opts).join(" ");
}
