// scripts/x/lib/twitter-util.mjs
// X の Snowflake ツイートID には作成時刻が埋め込まれている。
// → URLだけから投稿日時・経過日数を算出できる（API不要・$0）。
const TWITTER_EPOCH = 1288834974657n; // 2010-11-04 のミリ秒

export function extractTweetId(url) {
  const m = (url || "").match(/\/status\/(\d+)/);
  return m ? m[1] : null;
}

// ツイート作成時刻(ms)。算出不可なら null。
export function tweetCreatedAtMs(url) {
  const id = extractTweetId(url);
  if (!id) return null;
  try {
    return Number((BigInt(id) >> 22n) + TWITTER_EPOCH);
  } catch {
    return null;
  }
}

// 元投稿からの経過日数。算出不可なら null。
export function tweetAgeDays(url) {
  const ms = tweetCreatedAtMs(url);
  if (ms == null) return null;
  return (Date.now() - ms) / 86400000;
}
