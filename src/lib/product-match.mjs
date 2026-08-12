/**
 * 商品名の照合ロジック（共通モジュール）
 *
 * 「検索結果ページ行きのアフィリエイトリンクを、商品ページ直リンクに置き換える」
 * 処理は楽天とAmazonで共通なので、判定部分をここに集約する。
 *
 * 2026-08-05〜06 に楽天側（fix-search-affiliate-links.mjs）で実測しながら
 * 調整した結果を反映している。主な知見:
 *  - 検索語が多いほど0件になる。英字ブランド＋カタカナ商品名の二重付与が致命的
 *  - ブランド名だけの検索は同ブランドの別商品を掴む
 *  - 中古は転売価格で吊り上がり、価格判定を壊す
 *  - 「〜用インナー」等の付属品は商品名の語を全部含むので一致率100%になる
 *  - 短縮判定を sanitize 後の文字列で行うと「パンダTC+」と「パンダTC」、
 *    「まな板 M」と「まな板」が同一視され、取り違えを見逃す
 *
 * ※ fix-search-affiliate-links.mjs は実運用中のため、まだ自前の実装を持つ。
 *   次に触るときにこのモジュールへ寄せる。
 */

// 型番抽出: 「PA-F85A」「ST-310」「YEC-M03」のような英数ハイフン列
export function modelNumbers(name) {
  return (name.match(/[A-Za-z]{1,6}-?[0-9]{2,5}[A-Za-z0-9+/]*/g) || []).map((s) =>
    s.toUpperCase().replace(/-/g, "")
  );
}

// 世代表記のローマ数字を算用数字に寄せる。
// 「スパイスボックスII」と「スパイスボックス2」、「ステイシーST-II」と「ST-2」が
// 別物として扱われ、一致率50%で落ちていた（2026-08-06に21件を精査して判明）。
// 英字に挟まれたものは除外する（UVカット の V などを壊さないため）
const ROMAN_MAP = { i: "1", ii: "2", iii: "3", iv: "4", v: "5", vi: "6", vii: "7", viii: "8", ix: "9", x: "10" };
export function normalizeNumerals(s) {
  return s
    .replace(/[ⅠⅡⅢⅣⅤⅥⅦⅧⅨⅩ]/g, (c) => String("ⅠⅡⅢⅣⅤⅥⅦⅧⅨⅩ".indexOf(c) + 1))
    .replace(/[ⅰⅱⅲⅳⅴⅵⅶⅷⅸⅹ]/g, (c) => String("ⅰⅱⅲⅳⅴⅵⅶⅷⅸⅹ".indexOf(c) + 1))
    .replace(/(?<![A-Za-z0-9])(viii|vii|iii|ix|iv|vi|ii|x|v)(?![A-Za-z0-9])/gi, (m) => ROMAN_MAP[m.toLowerCase()] || m);
}

/** 商品名の語が、候補の商品名にどれだけ含まれるか（0〜1） */
export function tokenOverlap(a, b) {
  const tok = (s) =>
    new Set(
      normalizeNumerals(s)
        .toLowerCase()
        .replace(/[（(].*?[)）]/g, " ")
        .split(/[\s/／|｜・、。×]+/)
        .filter((t) => t.length >= 2)
    );
  const ta = tok(a);
  const tb = tok(b);
  if (ta.size === 0) return 0;
  let hit = 0;
  for (const t of ta) if ([...tb].some((u) => u.includes(t) || t.includes(u))) hit++;
  return hit / ta.size;
}

// 楽天APIは1文字の単語を含むキーワードを400で拒否する。記号も検索を狂わせる。
// ただしこの制約は楽天固有で、Amazonに持ち込むと世代番号が消えて事故る
// （「EcoFlow WAVE 2」→「EcoFlow WAVE」で WAVE 3 を掴んだ／2026-08-07）。
// Amazon側は minTokenLength: 1 を渡して1文字語を残すこと
export function sanitizeKeyword(s, { minTokenLength = 2 } = {}) {
  return s
    .replace(/[（(].*?[)）]/g, " ") // 括弧内の補足はAND条件を増やすだけで当たらない
    .replace(/[×\/＋+|｜]/g, " ")
    .split(/\s+/)
    .filter((t) => [...t].length >= minTokenLength)
    .join(" ")
    .slice(0, 120);
}

/**
 * 検索キーワードを「絞り込みが強い順」に並べる。当たった時点で打ち切る前提。
 * ブランド名だけ（およびその断片）は別商品を掴むので除外する。
 */
export function keywordLadder(product, opts = {}) {
  const name = product.name || "";
  const brand = product.brand && !name.includes(product.brand) ? `${product.brand} ` : "";
  const asciiBrandOnly = /^[\x20-\x7E]+$/.test((product.brand || "").trim());
  const tokens = sanitizeKeyword(name, opts).split(/\s+/).filter(Boolean);
  const models =
    name.match(/[A-Za-z]{1,6}-[A-Za-z0-9]{2,10}|[A-Za-z]{2,6}[0-9]{2,5}[A-Za-z0-9]*/g) || [];
  const brandWord = (product.brand || tokens[0] || "").slice(0, 20);

  const ladder = [`${brand}${name}`, name];
  if (asciiBrandOnly && product.brand) ladder.push(name.replace(product.brand, "").trim());
  if (tokens.length > 3) ladder.push(tokens.slice(0, 3).join(" "));
  if (tokens.length > 2) ladder.push(tokens.slice(0, 2).join(" "));
  if (models.length > 0) ladder.push(`${brandWord} ${models[0]}`, models[0]);

  const brandTokens = new Set(
    sanitizeKeyword(product.brand || "", opts).toLowerCase().split(/\s+/).filter(Boolean)
  );
  const isBrandOnly = (k) => {
    if (brandTokens.size === 0) return false;
    const t = k.toLowerCase().split(/\s+/).filter(Boolean);
    return t.length > 0 && t.every((x) => brandTokens.has(x));
  };

  const seen = new Set();
  return ladder
    .map((k) => sanitizeKeyword(k || "", opts))
    .filter((k) => {
      if (!k || seen.has(k) || isBrandOnly(k)) return false;
      seen.add(k);
      return true;
    });
}

/**
 * 商品名の語を削って検索したか。
 * 比較は sanitizeKeyword を通す前の生の名前で行う（1文字語と記号が消えるため）
 */
export function isShortenedKeyword(productName, keyword) {
  const tok = (s) =>
    s.toLowerCase().replace(/[（(].*?[)）]/g, " ").split(/[\s/／|｜・、。×]+/).filter(Boolean);
  const want = tok(productName);
  const got = tok(keyword);
  return !want.every((t) => got.some((g) => g === t || (t.length >= 2 && g.includes(t))));
}

/**
 * 商品名にある数字が候補側に無いか（世代・容量の取り違え検知）。
 * tokenOverlap は2文字未満の語を落とすので「WAVE 2」と「WAVE 3」が一致率100%になり、
 * さらに部分一致なので「2」は候補の「2026年新型」にも当たってしまう。
 * 数字の並びだけを完全一致で突き合わせて、この抜け道を塞ぐ。
 * 「丸洗いスランバーシュラフ・2」と「丸洗いスランバーシュラフ2」のように
 * 区切りが違うだけの表記は、数字列そのものを見るので拾える。
 */
export function generationMismatch(productName, itemName) {
  const runs = (s) => normalizeNumerals(s).match(/\d+/g) || [];
  const want = runs(productName);
  if (want.length === 0) return false;
  const got = new Set(runs(itemName));
  return want.some((n) => !got.has(n));
}

/**
 * 型番が一致するか。カラー等の英字接尾辞は同一商品として許す（BD-347 と BD-347BR）。
 * ただし数字が伸びるものは別品番として扱う。
 * 以前は単純な startsWith だったため REF-025 が REF-0254 に一致し、
 * サーモスのソフトクーラーがペット用ブラシを指していた（2026-08-11に発覚）。
 * 型番一致は信頼度「高」で自動適用されるので、ここが緩いと目視をすり抜ける。
 */
export function modelsMatch(productModels, itemModels) {
  return productModels.some((m) =>
    itemModels.some((im) => im === m || (im.startsWith(m) && /^[A-Za-z]/.test(im.slice(m.length))))
  );
}

/**
 * 高: 型番一致。カラー接尾辞まで照合するので取り違えにくい
 * 中: 商品名の語を1つも削らずに検索して一致率100%
 * 低: 一致率100%未満、またはキーワードを短縮
 */
export function confidenceTier(reason, overlap, shortened) {
  if (String(reason).startsWith("型番一致")) return "高";
  if (overlap >= 1 && !shortened) return "中";
  return "低";
}

// 中古は転売価格で吊り上がり、価格判定を壊す。店名が中立でも商品名に入る
export const USED_ITEM_PATTERNS =
  /【中古】|中古品|\bUSED\b|ユーズド|中古美品|訳あり|ジャンク|展示品|開封済|再生品/i;

// 本体ではなく付属品・互換品を掴む事故を防ぐ。
// 「〜用」と部品名の間に修飾語が入る出品が多いので数語挟んでも拾う
export const ACCESSORY_PATTERNS =
  /専用|互換|交換用|補修用|パーツ|オプション|別売|用.{0,12}?(?:インナー|カバー|ケース|シート|マット|ポール|ゴトク|フレーム|収納袋|スカート)/;

/** 商品側に無く候補側にだけ付属品マーカーがある場合のみ true（商品自体が付属品なら false） */
export function isAccessoryMismatch(productName, itemName) {
  return ACCESSORY_PATTERNS.test(itemName) && !ACCESSORY_PATTERNS.test(productName);
}

// ST/LX はコールマンのグレード表記（ツーリングドーム ST / LX）。
// 数字が無いので世代判定に引っかからず、実際に tent-duo-001（LX）へ
// ST の ASIN が付く取り違えが起きていた（2026-08-07）
export function sizeToken(name) {
  const m = name.match(/(?:^|[\s／/])([SML]|XL|LX|ST|\d型)(?=$|[\s／/（(])/);
  return m ? m[1] : null;
}

/** 商品名に単独のサイズ表記がある場合、候補にも同じサイズが必要 */
export function sizeMatches(productName, itemName) {
  const size = sizeToken(productName);
  if (!size) return true;
  // 「クロノスドーム 2型」と「クロノスドーム2」は同じ製品。
  // 型番的な世代表記は「型」の有無で表記が揺れるので両方見る
  const m = size.match(/^(\d)型$/);
  if (m) {
    const n = m[1];
    return new RegExp(`${n}\\s*型|[ァ-ヶー一-龠A-Za-z]${n}(?![0-9])`).test(itemName);
  }
  const re = new RegExp(
    `(?:^|[\\s／/｜|（(【])${size}(?=$|[\\s／/｜|）)】])|(?:ドーム|テント|タープ|シェルター|サイズ)\\s?${size}(?![A-Za-z0-9])`
  );
  return (
    re.test(itemName) ||
    itemName.includes(` ${size} `) ||
    itemName.endsWith(` ${size}`) ||
    itemName.includes(`${size}サイズ`) ||
    new RegExp(`[0-9ァ-ヶー一-龠]${size}(?![A-Za-z0-9])`).test(itemName)
  );
}

// 価格ゲートは非対称にする。
// 下限は付属品・部品を掴む事故の防波堤なので厳しく保ち、
// 上限は値上げ・円安で登録価格が古くなっている実態に合わせて緩める
export const PRICE_MIN_RATIO = 0.6;
export const PRICE_MAX_RATIO = 2.0;

export function priceInRange(productPrice, itemPrice, min = PRICE_MIN_RATIO, max = PRICE_MAX_RATIO) {
  if (!productPrice) return true;
  if (typeof itemPrice !== "number") return false;
  return itemPrice >= productPrice * min && itemPrice <= productPrice * max;
}

/**
 * 候補から本体らしくないものを落とす。
 * shopName はAmazonには無いので任意
 */
export function survivingCandidates(product, items, { usedShopPattern } = {}) {
  return items.filter((it) => {
    const title = it.title || "";
    if (usedShopPattern && usedShopPattern.test(it.shopName || "")) return false;
    if (USED_ITEM_PATTERNS.test(title)) return false;
    if (isAccessoryMismatch(product.name, title)) return false;
    if (!sizeMatches(product.name, title)) return false;
    return true;
  });
}

/**
 * 候補から採用する1件を選ぶ。items は {title, price, ...} に正規化しておくこと。
 * 採用理由と一致率を添えて返す。該当なしは null
 */
export function pickBest(product, items, opts = {}) {
  const models = modelNumbers(product.name);
  const survivors = survivingCandidates(product, items, opts);
  for (const item of survivors) {
    const itemModels = modelNumbers(item.title || "");
    const overlap = tokenOverlap(product.name, item.title || "");
    const priceOk = priceInRange(product.price, item.price, opts.priceMin, opts.priceMax);
    if (models.length > 0) {
      if (modelsMatch(models, itemModels)) {
        return { item, reason: `型番一致(${models[0]})`, overlap };
      }
    } else if (overlap >= 0.7 && priceOk) {
      return { item, reason: `名称一致${Math.round(overlap * 100)}%+価格整合`, overlap };
    }
  }
  return null;
}
