#!/usr/bin/env node
/**
 * 登録価格と実売価格の突き合わせ（両モール）
 *
 * 背景（2026-08-11）: 楽天リンクの照合中、候補は正しいのに「価格乖離」で
 * 落ちるものが続いた。中身を見ると**登録価格のほうが誤っていた**。
 *   スノーピーク アメニティドームS  登録¥44,000 / 公式店の実売¥19,800
 *     （Mサイズの価格がSに入っていると思われる）
 *   タトンカ Tarp 4 TC             登録¥80,233 / 同シリーズTarp 1が¥15,499
 * スクリプトが出す「最有力候補の実売/登録価格の中央値=112%」も、
 * 全体として登録価格が古い方向にずれていることを示していた。
 *
 * 価格が誤っていると二重に損をする:
 *  - サイトに嘘の値段が出る（リンク切れより読者の信頼を削る）
 *  - 価格ゲート（登録価格の60〜200%）が正しい候補を弾き、リンク修復が進まない
 *
 * 実売の取り方は「その商品ページそのもの」を引く。検索で拾い直すと
 * 別商品を掴むので、照合の意味がなくなる。
 *   Amazon … amazonUrl のASIN → Creators API getItems
 *   楽天   … affiliateUrl の店舗コードで店舗内検索し、itemUrl が一致するものを採用
 *            （itemCode 直引きは 400 "itemCode is not valid" で使えなかった）
 *
 * 2026-08-11 追記: Amazon単独では価格の誤りと「ASINが別商品を指している」を
 * 区別できない。実際、最初の実行で上位に並んだ マナイタセットM 512% /
 * 山専ボトル 6% / ヘリノックス ビーチチェア 26% は、いずれも
 * price-held-back.json で誤ASINを疑っていた商品だった。
 * 価格だけ見て直すと、誤ったASINの値段を正として書き込んでしまう。
 * 商品名とストア側のタイトルを突き合わせ、一致率50%未満は
 * 「リンクの問題」として価格の話から切り離す。
 *
 * 使い方（Macで実行。両APIの認証情報が必要。楽天はIP許可リストも）:
 *   node scripts/audit-prices.mjs                 # 監査のみ（書き込まない）
 *   node scripts/audit-prices.mjs --limit 50      # 件数を絞って試す
 *   node scripts/audit-prices.mjs --ids tarp-007  # 特定商品の登録価格だけ確かめる
 *   node scripts/audit-prices.mjs --apply         # 両モールが一致した分だけ直す
 *   node scripts/audit-prices.mjs --lowest        # 両モールが揃っている商品の最安を提案
 *   node scripts/audit-prices.mjs --lowest --apply
 *
 * --apply が直すのは「両モールの実売が10%以内で一致し、かつ登録価格から
 * 20%以上ずれている」ものだけ。片方しか取れないものは人間に回す。
 */
import fs from "node:fs";
import path from "node:path";
import dns from "node:dns";
import { fileURLToPath } from "node:url";
import { loadEnv } from "../src/lib/x-agent-utils.mjs";
import { creatorsApi, credentials, hasCredentials, asinOf } from "../src/lib/amazon-creators-api.mjs";
import {
  tokenOverlap,
  sanitizeKeyword,
  modelNumbers,
  normalizeBrands,
  brandMatches,
} from "../src/lib/product-match.mjs";

dns.setDefaultResultOrder("ipv4first");
loadEnv();

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const ROOT = path.join(__dirname, "..");
const PRODUCTS = path.join(ROOT, "data", "products.json");
const ARTICLES = path.join(ROOT, "data", "articles.json");
const OUT = path.join(ROOT, "scratch", "price-audit.json");

const argv = process.argv.slice(2);
const APPLY = argv.includes("--apply");
// 「両モールで実売が違うときは安いほうを表示する」方針（2026-08-16 決定）。
//
// ただし片方しか取れない商品には使えない。楽天だけ取れている商品は
// その値が唯一の実売なので自動的に「最安」になるが、実際は転売出品の
// ことがある（パイルドライバー 登録¥7,150 に対し楽天¥23,000＝322%。
// 定価は7,000円台で、登録価格のほうが正しい）。
// 両モールの値が揃っているものだけを対象にする
const LOWEST = argv.includes("--lowest");
const argVal = (n) => {
  const i = argv.indexOf(n);
  return i !== -1 && argv[i + 1] ? argv[i + 1] : null;
};
const LIMIT = parseInt(argVal("--limit") || "", 10) || Infinity;
// 特定の商品だけ調べたい場合。1件の登録価格を確かめるのに全件回すのは無駄
const IDS = new Set((argVal("--ids") || "").split(",").map((s) => s.trim()).filter(Boolean));

const RAKUTEN_API = "https://openapi.rakuten.co.jp/ichibams/api/IchibaItem/Search/20220601";
const appId = process.env.RAKUTEN_APP_ID;
const accessKey = process.env.RAKUTEN_ACCESS_KEY;
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const decode = (s) => {
  try {
    return decodeURIComponent(s);
  } catch {
    return s;
  }
};

if (!hasCredentials() && !appId) {
  console.error("Amazon / 楽天いずれの認証情報もありません（.env.local を確認）");
  process.exit(1);
}

/**
 * アフィリエイトURLから楽天の店舗コードと商品URLコードを取り出す。
 * item.rakuten.co.jp/{shopCode}/{urlCode}/
 */
function rakutenRef(affiliateUrl) {
  const m = decode(affiliateUrl || "").match(/item\.rakuten\.co\.jp\/([^/]+)\/([^/?&]+)/);
  return m ? { shopCode: m[1], urlCode: m[2] } : null;
}

// タイトルに選択肢が並んでいれば、サイズ・色を選ばせる親ページとみなす。
//   「サイズ LDX+/MDX+」「3人用/４人用/6人用」「各色」「25~35リットル」
// 全角数字・全角スラッシュがあるので NFKC で正規化してから見る。
//
// 「〜人用」の範囲は除く。「カマボコテント3M【4～5人用】」はテント1張りの
// 収容人数であって選択肢ではない。スラッシュ区切りの「3人用/4人用/6人用」は
// 選択肢なので、そちらだけ拾う
function looksLikeVariationParent(title) {
  const t = (title || "").normalize("NFKC");
  return (
    /各色|各サイズ|全[0-9]+色/.test(t) ||
    /[0-9]+人用\s*\/\s*[0-9]+人用/.test(t) ||
    /サイズ\s*[A-Za-z0-9+]+\s*\/\s*[A-Za-z0-9+]+/.test(t) ||
    /[0-9]+\s*[~〜]\s*[0-9]+\s*(リットル|L|cm)\b/.test(t)
  );
}

let rakutenFailures = 0;
let perItemErrors = 0;
let rateLimited = 0;
/**
 * その商品ページの価格を引く。
 *
 * 当初 itemCode（shop:code）で直引きしたが全件 400 "itemCode is not valid" だった。
 * URLのパス末尾は楽天の itemCode とは別物で、この形では受け付けられない。
 * 代わりに shopCode で店舗内を検索し、itemUrl が一致するものを拾う。
 * 検索なので取り違えの余地があるが、URL完全一致を条件にするので実質直引きと同じ。
 */
async function rakutenPrice(ref, productName) {
  if (!appId || rakutenFailures >= 5) return null;
  const attempt = async (keyword) => {
    const params = new URLSearchParams({
      applicationId: appId,
      ...(accessKey ? { accessKey } : {}),
      shopCode: ref.shopCode,
      keyword: sanitizeKeyword(keyword).slice(0, 100),
      hits: "30",
      format: "json",
      formatVersion: "2",
    });
    const res = await fetch(`${RAKUTEN_API}?${params}`, {
      headers: { Origin: "https://camp-gear-lab.com", Referer: "https://camp-gear-lab.com/" },
    });
    // 429（レート超過）は待てば通る。打ち切りに数えない
    if (res.status === 429) {
      rateLimited++;
      await sleep(1600);
      const retry = await fetch(`${RAKUTEN_API}?${params}`, {
        headers: { Origin: "https://camp-gear-lab.com", Referer: "https://camp-gear-lab.com/" },
      });
      if (!retry.ok) return null;
      return pickItem(await retry.json());
    }
    if (!res.ok) {
      const body = await res.text().catch(() => "");
      // 打ち切りに数えるのは設定の問題（認証・IP制限）だけ。
      // shopCode が無効といった商品固有の400で全体を止めると、
      // 1件のデータ不備で残り122件の照合を失う（2026-08-11に発生）
      // 設定の問題は店舗をまたいで全部落ちる。商品固有のエラーに混ぜてはいけない。
      //
      // 2026-08-16: "API Configuration not found" が520件出たのに、これを
      // 商品固有として1件ずつスキップし続け、楽天の価格が1件も取れないまま
      // 完走した。レポートは正常な顔をしていて「安いほうに合わせる対象0件」
      // という結論まで出した。実際は両モールが揃った商品が消えていただけ。
      // 誤リンクの検出数も5件→3件に減ったが、これは改善ではなく
      // 楽天側が見えなくなっただけだった
      const isAuth =
        /CLIENT_IP_NOT_ALLOWED|API Configuration not found|invalid.*applicationId/i.test(body) ||
        res.status === 401 ||
        res.status === 403;
      if (!isAuth) {
        if (++perItemErrors <= 5) {
          console.warn(`\n  楽天API ${res.status}（${ref.shopCode}）: ${body.slice(0, 120)}  ← この商品のみスキップ`);
        }
        return null;
      }
      if (++rakutenFailures <= 2) {
        console.warn(`\n  楽天API ${res.status}（${ref.shopCode}）: ${body.slice(0, 160)}`);
      }
      if (rakutenFailures === 5) {
        console.warn(
          "\n  IP制限で拒否されています。curl -4 -s ifconfig.me のIPを許可リストへ。" +
            "以降はAmazonのみで判定します\n"
        );
      }
      return null;
    }
    return pickItem(await res.json());
  };

  // 同じ商品ページのものだけ採用する。店舗内の別商品を掴んでは意味がない
  function pickItem(data) {
    const hit = (data.Items || []).find((it) =>
      decode(it.itemUrl || "").includes(`/${ref.urlCode}`)
    );
    return hit ? { price: hit.itemPrice, name: hit.itemName } : null;
  }

  try {
    const first = await attempt(productName);
    if (first) return first;
    // 楽天の規定は「1つのapplication_idにつき1秒に1回以下」。
    // ここは1商品で2回投げる箇所で、700msしか空けていなかった＝規定違反。
    // 360商品×2回を1日に何度も流していたので、application_id が
    // 利用停止になった可能性がある（2026-08-23に API Configuration not found
    // が全リクエストで返るようになった件の有力な候補）。
    // 待ち時間は規定より短くしない。速度より止まらないことを優先する
    await sleep(1200);
    return await attempt(ref.urlCode);
  } catch {
    return null;
  }
}

// ─── 本処理 ──────────────────────────────────────────
const products = JSON.parse(fs.readFileSync(PRODUCTS, "utf8"));
const articles = JSON.parse(fs.readFileSync(ARTICLES, "utf8"));

// 記事露出。同じ間違いでも読まれている商品ほど実害が大きい
const exposure = new Map();
for (const a of articles) {
  if (a.status !== "published") continue;
  const ids = new Set(a.productIds || []);
  for (const m of (a.content || "").matchAll(/\{\{(?:product|comparison|ranking):([^}|]+)\}\}/g)) {
    for (const id of m[1].split(",")) ids.add(id.trim());
  }
  for (const id of ids) exposure.set(id, (exposure.get(id) || 0) + 1);
}

const targets = products
  .filter((p) => (IDS.size > 0 ? IDS.has(p.id) : true))
  .filter((p) => p.price && (asinOf(p.amazonUrl) || rakutenRef(p.affiliateUrl)))
  .sort((a, b) => (exposure.get(b.id) || 0) - (exposure.get(a.id) || 0))
  .slice(0, LIMIT);

if (IDS.size > 0) {
  const missing = [...IDS].filter((id) => !targets.some((p) => p.id === id));
  if (missing.length) console.log(`⚠ 対象外（価格未設定かリンク無し）: ${missing.join(", ")}\n`);
}

console.log(`価格監査: ${targets.length}件（${APPLY ? "APPLY" : "監査のみ"}）`);
console.log(`  Amazon: ${targets.filter((p) => asinOf(p.amazonUrl)).length}件 / 楽天: ${targets.filter((p) => rakutenRef(p.affiliateUrl)).length}件\n`);

// Amazon は10件ずつまとめて引ける
const amazonPrice = new Map();
if (hasCredentials()) {
  const withAsin = targets.filter((p) => asinOf(p.amazonUrl));
  const tag = credentials().partnerTag;
  for (let i = 0; i < withAsin.length; i += 10) {
    const batch = withAsin.slice(i, i + 10);
    try {
      const data = await creatorsApi("/catalog/v1/getItems", {
        itemIds: batch.map((p) => asinOf(p.amazonUrl)),
        partnerTag: tag,
        resources: ["itemInfo.title", "offersV2.listings.price"],
      });
      for (const it of data.itemsResult?.items || []) {
        const amount = it.offersV2?.listings?.[0]?.price?.money?.amount;
        // 価格が無い出品でもタイトルは必ず残す。
        //
        // 2026-08-16: 価格が取れたときだけ記録していたため、在庫切れ等で
        // offersV2 に価格が無いASINは名前まで捨てられ、**そのリンクが正しい
        // 商品を指しているかの判定自体が行われなくなっていた**。
        // 価格の話とリンクの話は別なので、片方が欠けてももう片方は続ける
        // 出品はあるのに price キーが無いASINがある。
        //
        // 2026-08-16: B0CYBKMWGS の応答が
        //   "offersV2": { "listings": [ { "isBuyBoxWinner": true, ... } ] }
        // で price ごと欠けていた。タイトルも「サイズ LDX+/MDX+」で、
        // サイズごとに値段が違うため単一価格を持たないバリエーション親だった。
        //
        // ただし「出品はあるが価格が無い」＝親ページ、ではない。実際に数えたら
        // 134件すべてがこの条件に当てはまり、中身は明らかに混ざっていた。
        //   「アメニティドーム 3人用/４人用/6人用」  → 親ページ
        //   「富士錦 パワー森林香(赤色) 30巻入り」    → 単一商品
        //   「SUO RING 28° ICE ネック用 (アイボリー, S)」→ 色・サイズ確定済み
        // 親ページはタイトルに選択肢が並ぶので、そこで見分ける。
        // 見分けられないものは「理由不明」として分けて出す。
        // 一括りにすると、直せる対象が埋もれる
        const hasListing = Boolean(it.offersV2?.listings?.length);
        const title = it.itemInfo?.title?.displayValue || "";
        amazonPrice.set(it.asin, {
          price: typeof amount === "number" ? Math.round(amount) : null,
          name: title,
          noPrice: typeof amount !== "number" && hasListing,
          parentLike: typeof amount !== "number" && hasListing && looksLikeVariationParent(title),
        });
      }
    } catch (e) {
      console.warn(`  Amazonバッチ${Math.floor(i / 10) + 1}失敗: ${String(e.message).slice(0, 60)}`);
    }
    process.stdout.write(`\r  Amazon ${Math.min(i + 10, withAsin.length)}/${withAsin.length}`);
    if (i + 10 < withAsin.length) await sleep(3000);
  }
  console.log("");
  // 価格が取れない件数を必ず出す。ここが多いと「両モール一致」が構造的に
  // 成立せず、価格の自動是正が黙って動かなくなる
  const vals = [...amazonPrice.values()];
  const noPrice = vals.filter((v) => v.price === null).length;
  const parentLike = vals.filter((v) => v.parentLike).length;
  console.log(
    `  Amazon: ${amazonPrice.size}件取得（価格なし ${noPrice}件 = ` +
      `サイズ選択ページ ${parentLike}件 + 理由不明 ${noPrice - parentLike}件）` +
      (noPrice > amazonPrice.size / 2
        ? "\n  ⚠ 半数以上で価格が取れていません。両モール照合が成立しないため --apply はほぼ何もしません"
        : "")
  );
}

// 楽天は1件ずつ。itemCode指定なので確実にその商品ページの値が返る
const results = [];
let done = 0;
for (const p of targets) {
  const asin = asinOf(p.amazonUrl);
  const ref = rakutenRef(p.affiliateUrl);
  const amz = asin ? amazonPrice.get(asin) : null;
  let rak = null;
  if (ref) {
    rak = await rakutenPrice(ref, p.name);
    await sleep(1100); // 楽天は毎秒1リクエストが目安
  }
  done++;
  process.stdout.write(`\r  楽天 ${done}/${targets.length}`);
  if (!amz && !rak) continue;

  const prices = [amz?.price, rak?.price].filter((x) => typeof x === "number" && x > 0);
  // タイトルだけ取れて価格が1つも無い場合がある（在庫切れのASINなど）。
  // 0除算で market/ratio が NaN になり中央値まで壊れるので null にする。
  // リンクの正誤判定は価格が無くても続ける
  const market = prices.length ? Math.round(prices.reduce((a, b) => a + b, 0) / prices.length) : null;
  const ratio = market === null ? null : market / p.price;
  // 両モールが互いに10%以内なら市場価格として信頼できる
  const agree =
    prices.length === 2 && Math.abs(prices[0] - prices[1]) / Math.max(...prices) <= 0.1;

  // 価格の誤りと「そもそも別商品を指している」は別問題で、混ぜると判断できない。
  // 価格だけ見て直すと、誤ったASINの値段を正として書き込んでしまう。
  // 商品名とストア側のタイトルを突き合わせて切り分ける。
  //
  // 半角カナのタイトルで一致率が落ちるので NFKC で正規化する
  // （「ﾀﾄﾝｶ ﾀｰﾌﾟ」が29%→43%になった）。
  // またタイトルが型番だけの出品（「IPP-2222G」）は一致率が構造的に低いので、
  // 型番が一致していれば別商品ではないと判断する
  const norm = (x) => (x || "").normalize("NFKC");
  // 型番は「独立した語」として現れる場合だけ一致とみなす。
  // 抽出値だけで比べると BUNDOK の BD-190 が
  // シャツの品番 LFTG-BD-190 の一部に一致してしまい、誤リンクを見逃す
  const rawModels = (norm(p.name).match(/[A-Za-z]{1,6}-?[0-9]{2,5}[A-Za-z0-9+/]*/g) || []);
  const sameModel = (title) => {
    const t = norm(title);
    return rawModels.some((m) => {
      const esc = m.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
      return new RegExp(`(?<![A-Za-z0-9-])${esc}(?![A-Za-z0-9])`, "i").test(t);
    });
  };
  const score = (title) =>
    sameModel(title)
      ? 1
      : tokenOverlap(
          normalizeBrands(norm(p.name).toLowerCase()),
          normalizeBrands(norm(title).toLowerCase())
        );
  const amzMatch = amz ? score(amz.name) : null;
  const rakMatch = rak ? score(rak.name) : null;
  // これは選別であって断定ではない。閾値を下げて拾いすぎない側に倒す。
  //
  // 一致率が低くてもブランドが合っていれば別商品とは断定しない。
  // カタカナと英語で商品名まで音訳されると語が1つも重ならず、
  // 「メレル モアブ3ミッド」と「MERRELL MOAB 3 GORE-TEX」が0%になる。
  // 語の一致率では原理的に解けないので、ブランドを別の軸として見る
  const suspect = (m, title) => m !== null && m < 0.4 && !brandMatches(p.brand, title);
  const wrongLink = suspect(amzMatch, amz?.name) || suspect(rakMatch, rak?.name);

  results.push({
    id: p.id,
    name: p.name,
    exposure: exposure.get(p.id) || 0,
    registered: p.price,
    amazon: amz?.price ?? null,
    rakuten: rak?.price ?? null,
    amazonTitle: amz?.name ?? null,
    amazonParentLike: Boolean(amz?.parentLike),
    amazonNoPrice: Boolean(amz?.noPrice),
    rakutenTitle: rak?.name ?? null,
    amazonMatch: amzMatch === null ? null : Math.round(amzMatch * 100),
    rakutenMatch: rakMatch === null ? null : Math.round(rakMatch * 100),
    wrongLink,
    market,
    ratio: ratio === null ? null : Math.round(ratio * 100),
    agree,
    sources: prices.length,
  });
}
console.log("\n");

// ─── 出力 ───────────────────────────────────────────
// 価格が取れなかったものは「ずれ」を計算できない。0扱いにすると
// 一致しているように見えてしまうので、並べ替えでは最後に回す
const off = (r) => (r.ratio === null ? -1 : Math.abs(r.ratio - 100));
const byImpact = (a, b) => b.exposure - a.exposure || off(b) - off(a);
const suspicious = results.filter((r) => off(r) >= 20).sort(byImpact);

// リンクが別商品を指しているものは価格の話ではない。先に切り出す。
//
// 2026-08-14: ここは suspicious（価格が20%以上ずれたもの）から絞っていた。
// そのせいで「別商品を指しているのに価格はたまたま合っている」ケースが
// 丸ごと消えていた。tarp-007 がまさにそれで、リンク先の LACITA のランタンが
// 偶然 ¥10,800 で登録価格と同額だったため、wrongLink: true がJSONに入って
// いるのに画面には「疑い0件」と出た。
//
// 値段が合っていることは、同じ商品である証拠にならない。
// リンクの正誤は価格と独立して判定する
const mislinked = results.filter((r) => r.wrongLink).sort(byImpact);
const priceOnly = suspicious.filter((r) => !r.wrongLink);
const confident = priceOnly.filter((r) => r.agree);
const single = priceOnly.filter((r) => !r.agree);

// 価格が取れていない出品は「¥null」ではなくそう書く。
// 値が無いことと値が0円であることは別で、null がそのまま出ると壊れて見える
const yen = (v) => (typeof v === "number" ? `¥${v.toLocaleString()}` : "価格取得できず");

const fmt = (r) =>
  `  ${String(r.exposure).padStart(2)}記事  ${r.id.padEnd(30)} ${r.name.slice(0, 26).padEnd(28)}\n` +
  `          登録¥${String(r.registered).padStart(7)}  →  実売¥${String(r.market).padStart(7)}（${r.ratio}%）` +
  `  Amazon:${r.amazon ? "¥" + r.amazon : "—"} 楽天:${r.rakuten ? "¥" + r.rakuten : "—"}`;

console.log(`── ⚠ リンクが別商品を指している疑い ${mislinked.length}件（要確認。価格ではなくリンクの問題）──`);
for (const r of mislinked) {
  console.log(`  ${String(r.exposure).padStart(2)}記事  ${r.id.padEnd(30)} ${r.name.slice(0, 30)}`);
  if (r.amazonTitle && r.amazonMatch < 50)
    console.log(`          Amazon一致${r.amazonMatch}%  ${yen(r.amazon)}  「${r.amazonTitle.slice(0, 46)}」`);
  if (r.rakutenTitle && r.rakutenMatch < 50)
    console.log(`          楽天一致${r.rakutenMatch}%  ${yen(r.rakuten)}  「${r.rakutenTitle.slice(0, 46)}」`);
}

// サイズ選択ページ（親ASIN）は、価格が取れないだけでなく購入導線としても弱い。
// 読者が自分でサイズを選ぶことになり、記事が薦めた型と違うものを買いうる
const parentAsins = results.filter((r) => r.amazonParentLike).sort(byImpact);
const noPriceUnknown = results.filter((r) => r.amazonNoPrice && !r.amazonParentLike).sort(byImpact);
const showList = (rows, n = 20) => {
  for (const r of rows.slice(0, n)) {
    console.log(`  ${String(r.exposure).padStart(2)}記事  ${r.id.padEnd(30)} ${r.name.slice(0, 26)}`);
    console.log(`          「${(r.amazonTitle || "").slice(0, 56)}」`);
  }
  if (rows.length > n) console.log(`  … 他${rows.length - n}件（レポート参照）`);
};

console.log(
  `\n── Amazonがサイズ選択ページ ${parentAsins.length}件（子ASINに張り替えたい）──`
);
showList(parentAsins);

console.log(
  `\n── Amazonの価格が返らない（理由不明）${noPriceUnknown.length}件` +
    `（在庫切れか、APIが価格を返さないだけか未確認）──`
);
showList(noPriceUnknown, 10);

// 両モールが揃っていて、安いほうが登録価格と10%以上ずれているもの。
// 誤リンクの疑いがあるものは価格の話ではないので外す
const lowestTargets = results
  .filter((r) => r.sources === 2 && !r.wrongLink)
  .map((r) => ({ ...r, lowest: Math.min(r.amazon, r.rakuten) }))
  .filter((r) => Math.abs(r.lowest / r.registered - 1) >= 0.1)
  .sort(byImpact);

if (LOWEST) {
  console.log(`\n── 安いほうに合わせる対象 ${lowestTargets.length}件（両モールが揃っているものだけ）──`);
  for (const r of lowestTargets) {
    console.log(
      `  ${String(r.exposure).padStart(2)}記事  ${r.id.padEnd(30)} ${r.name.slice(0, 24).padEnd(26)}\n` +
        `          登録¥${String(r.registered).padStart(7)}  →  ¥${String(r.lowest).padStart(7)}` +
        `   Amazon:${yen(r.amazon)} 楽天:${yen(r.rakuten)}`
    );
  }
  console.log(
    `\n  ※ 片方しか取れない商品は対象外です。唯一の実売が転売高値のことがあり、` +
      `\n    それを最安として書き込むと登録価格より悪化します`
  );
}

console.log(`\n── 両モールが一致して登録価格とずれる ${confident.length}件（確度が高い）──`);
for (const r of confident) console.log(fmt(r));

console.log(`\n── 片方しか取れない / 両モールが割れる ${single.length}件（要目視）──`);
for (const r of single.slice(0, 25)) console.log(fmt(r));
if (single.length > 25) console.log(`  … 他${single.length - 25}件（レポート参照）`);

const ratios = results.map((r) => r.ratio).filter((x) => typeof x === "number").sort((a, b) => a - b);
console.log(`\n── まとめ ──`);
console.log(`  照合できた商品: ${results.length}件`);
console.log(`  実売/登録 の中央値: ${ratios[Math.floor(ratios.length / 2)]}%`);
if (perItemErrors || rateLimited)
  console.log(`  楽天: 商品固有のエラー${perItemErrors}件 / レート超過で再試行${rateLimited}件`);
// リンクの疑いは価格のずれとは独立に数える（価格が合っていても別商品はある）
console.log(`  別商品を指している疑い: ${mislinked.length}件 ← リンクを直す話`);
console.log(`  サイズ選択ページ: ${parentAsins.length}件 ← 子ASINに張り替える話`);
console.log(`  価格が返らない（理由不明）: ${noPriceUnknown.length}件 ← 要調査`);
console.log(`  20%以上ずれ: ${suspicious.length}件`);
console.log(`    ├ 両モール一致（価格が誤り）: ${confident.length}件 ← --apply で直せる`);
console.log(`    └ 片方のみ・要目視: ${single.length}件`);

if (APPLY) {
  const ts = new Date().toISOString();
  const byId = new Map(products.map((p) => [p.id, p]));
  const applySet = LOWEST
    ? lowestTargets.map((r) => ({ id: r.id, to: r.lowest }))
    : confident.map((r) => ({ id: r.id, to: r.market }));
  let n = 0;
  for (const r of applySet) {
    const p = byId.get(r.id);
    if (!p) continue;
    console.log(`  ¥${p.price} → ¥${r.to}  ${p.name.slice(0, 34)}`);
    p.price = r.to;
    p.updatedAt = ts; // 進めないと同期のauto-pullで巻き戻る
    n++;
  }
  fs.writeFileSync(PRODUCTS, JSON.stringify(products, null, 2));
  console.log(
    `\nproducts.json 反映: ${n}件（${LOWEST ? "両モールが揃った商品の最安" : "両モール一致分のみ"}）`
  );
  console.log("次: git diff で確認 → npm run db:sync -- --no-pull");
} else {
  console.log(
    LOWEST
      ? "\n適用: --lowest --apply … 上の一覧を安いほうの価格に書き換えます"
      : "\n適用: --apply … 両モールが一致した分だけ登録価格を直します" +
          `\n      --lowest … 両モールが揃った${lowestTargets.length}件を安いほうに合わせる案を出します`
  );
}

// 楽天が広範に落ちた回の結果で価格を判断すると、片方だけ見て決めることになる。
// 「両モールが揃っている」前提が崩れているのに、見た目は完走したレポートになる
const rakutenTargets = targets.filter((p) => rakutenRef(p.affiliateUrl)).length;
if (rakutenTargets > 0 && perItemErrors > rakutenTargets * 0.2) {
  console.log(
    `\n🛑 楽天が広範に失敗しています（${perItemErrors}件 / 対象${rakutenTargets}件）。` +
      `\n   この結果は楽天側が欠けた状態です。価格の判断・--apply は行わないでください。` +
      `\n   楽天APIのアプリ設定（applicationId / accessKey）とIP許可リストを確認してください。`
  );
}

fs.mkdirSync(path.dirname(OUT), { recursive: true });
fs.writeFileSync(OUT, JSON.stringify({ ranAt: new Date().toISOString(), results, mislinked, parentAsins, noPriceUnknown, confident, single }, null, 2));
console.log(`レポート: ${OUT}`);
