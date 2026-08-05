#!/usr/bin/env node
/**
 * 検索ページ行きアフィリリンクの商品直リンク化
 *
 * 背景（2026-08-01 EPC分析）: products.json の affiliateUrl のうち194件が
 * 楽天の「検索結果ページ」に飛ぶリンクだった。7月最多クリック商品の
 * コロナ PA-F85A（511クリック）が楽天成果ゼロで発覚。検索結果に着地した
 * 読者は迷子になり、直接成約しない。
 *
 * このスクリプトは楽天Ichiba APIで各商品の実商品ページを探し、
 * APIが返すアフィリエイトURL（アフィリエイトID込み）に置き換える。
 *
 * 使い方（Macで実行。RAKUTEN_APP_ID / RAKUTEN_ACCESS_KEY が必要）:
 *   node scripts/fix-search-affiliate-links.mjs           # dry-run（提案のみ）
 *   node scripts/fix-search-affiliate-links.mjs --apply   # products.jsonへ反映
 *   node scripts/fix-search-affiliate-links.mjs --limit 20  # 先頭N件だけ処理
 *
 * 安全装置:
 * - 商品名に型番らしき文字列がある場合、候補の商品名にも同じ型番が
 *   含まれない限り採用しない
 * - 型番がない場合は、名前トークンの一致率と価格の乖離（±40%以内）で判定
 * - 確信が持てない商品はスキップして手動リストに出す（誤リンクは検索リンクより害が大きい）
 * - dry-run がデフォルト。--apply でも scratch/affiliate-link-fixes.json に
 *   全変更履歴を残す
 */
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { loadEnv } from "../src/lib/x-agent-utils.mjs";

// .env.local を自前で読む（手動 export は値に空白を含む変数で事故を起こす）
loadEnv();

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const ROOT = path.join(__dirname, "..");
const PRODUCTS = path.join(ROOT, "data", "products.json");
const REPORT = path.join(ROOT, "scratch", "affiliate-link-fixes.json");

const RAKUTEN_API_URL =
  "https://openapi.rakuten.co.jp/ichibams/api/IchibaItem/Search/20220601";
// accessKeyのIP許可リストで弾かれたとき用（外出先など）。IP制限が無い従来系
const RAKUTEN_API_URL_LEGACY =
  "https://app.rakuten.co.jp/services/api/IchibaItem/Search/20220601";
let useLegacy = false;
const RAKUTEN_AFFILIATE_ID =
  process.env.RAKUTEN_AFFILIATE_ID || "18eb3228.621d8df3.18eb3229.ec5f8d49";

const APPLY = process.argv.includes("--apply");
// 診断モード。判定は一切変えず、スキップ理由の内訳だけを追加で出す
const EXPLAIN = process.argv.includes("--explain");
const limitIdx = process.argv.indexOf("--limit");
const LIMIT =
  limitIdx !== -1 ? parseInt(process.argv[limitIdx + 1], 10) : Infinity;

const appId = process.env.RAKUTEN_APP_ID;
const accessKey = process.env.RAKUTEN_ACCESS_KEY;
if (!appId || !accessKey) {
  console.error("RAKUTEN_APP_ID / RAKUTEN_ACCESS_KEY が未設定です（Macの環境変数を確認）");
  process.exit(1);
}

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

function isSearchLink(affiliateUrl) {
  if (!affiliateUrl) return false;
  const m = affiliateUrl.match(/[?&]pc=([^&]+)/);
  if (!m) return false;
  // 一部商品のpc=値はエンコードが壊れていてdecodeURIComponentが例外を投げる。
  // デコードできない場合は生文字列で判定する（%2F区切りでも部分一致する）
  let target;
  try {
    target = decodeURIComponent(m[1]);
  } catch {
    target = m[1];
  }
  return target.includes("search.rakuten.co.jp");
}

// 型番抽出: 「PA-F85A」「ST-310」「YEC-M03」のような英数ハイフン列
function modelNumbers(name) {
  return (name.match(/[A-Za-z]{1,6}-?[0-9]{2,5}[A-Za-z0-9+/]*/g) || []).map(
    (s) => s.toUpperCase().replace(/-/g, "")
  );
}

function tokenOverlap(a, b) {
  const tok = (s) =>
    new Set(
      s
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

// 楽天APIは1文字の単語を含むキーワードを400で拒否する（各単語2文字以上の制約）。
// 「アメニティドーム L」「カマボコテント3 M」等が全滅していた原因。
// 記号（×・/・＋）も除去する
function sanitizeKeyword(s) {
  return s
    .replace(/[（(].*?[)）]/g, " ") // 括弧内の補足はAND条件を増やすだけで当たらない
    .replace(/[×\/＋+|｜]/g, " ")
    .split(/\s+/)
    .filter((t) => [...t].length >= 2)
    .join(" ")
    .slice(0, 120);
}

// 楽天はキーワードをAND検索するため、語が多いほど0件になりやすい。
// 英字ブランド＋カタカナ商品名の二重付与が特に効いていた
//（例「Therm-a-Rest サーマレスト ネオエアーピロー」→ 0件）。
// 広い順ではなく「絞り込みが強い順」に試し、当たった時点で打ち切る。
function keywordLadder(product) {
  const name = product.name || "";
  const brand = product.brand && !name.includes(product.brand) ? `${product.brand} ` : "";
  const asciiBrandOnly = /^[\x20-\x7E]+$/.test((product.brand || "").trim());
  const bare = sanitizeKeyword(name);
  const tokens = bare.split(/\s+/).filter(Boolean);
  const models =
    name.match(/[A-Za-z]{1,6}-[A-Za-z0-9]{2,10}|[A-Za-z]{2,6}[0-9]{2,5}[A-Za-z0-9]*/g) || [];
  const brandWord = (product.brand || tokens[0] || "").slice(0, 20);

  const ladder = [`${brand}${name}`, name];
  // 英字ブランドは店舗表記と食い違いやすいので、外した形も試す
  if (asciiBrandOnly && product.brand) ladder.push(name.replace(product.brand, "").trim());
  if (tokens.length > 3) ladder.push(tokens.slice(0, 3).join(" "));
  if (tokens.length > 2) ladder.push(tokens.slice(0, 2).join(" "));
  if (models.length > 0) ladder.push(`${brandWord} ${models[0]}`, models[0]);

  // 正規化して重複と空を落とす
  const seen = new Set();
  return ladder
    .map((k) => sanitizeKeyword(k || ""))
    .filter((k) => {
      if (!k || seen.has(k)) return false;
      seen.add(k);
      return true;
    });
}

// 中古・リユース店は除外（新品を勧める記事から中古在庫に飛ばさない）
const USED_SHOP_PATTERNS = /2nd STREET|セカンドストリート|ワットマン|リサイクル|中古|質屋|ブックオフ|BOOKOFF|トレファク|セカスト/i;

// 店名が中立でも商品名に【中古】が入る出品が多い（例: アトリエ絵利奈・ドリエム）。
// 中古は転売価格で吊り上がり、価格判定を壊すので商品名でも弾く。
const USED_ITEM_PATTERNS = /【中古】|中古品|\bUSED\b|ユーズド|中古美品|訳あり|ジャンク|展示品|開封済/i;

// 本体ではなく付属品・互換品を掴む事故を防ぐ。
// 商品名側に無く、候補側にだけ現れた場合のみ除外する
// （商品自体が「〜用インナー」なら正規の一致なので落としてはいけない）
// 「〜用」と部品名の間に修飾語が入る出品が多いため、間に数語挟んでも拾う
// 例:「パンダ TC プラス用 スタンダード インナー」
const ACCESSORY_PATTERNS =
  /専用|互換|交換用|補修用|パーツ|オプション|別売|用.{0,12}?(?:インナー|カバー|ケース|シート|マット|ポール|ゴトク|フレーム|収納袋|スカート)/;

function isAccessoryMismatch(productName, itemName) {
  return ACCESSORY_PATTERNS.test(itemName) && !ACCESSORY_PATTERNS.test(productName);
}

async function searchRakuten(keyword) {
  const params = new URLSearchParams({
    applicationId: appId,
    ...(useLegacy ? {} : { accessKey }), // 従来系はaccessKeyを受け付けない
    affiliateId: RAKUTEN_AFFILIATE_ID,
    keyword: sanitizeKeyword(keyword),
    hits: "10",
    sort: "standard", // 検索妥当性順（レビュー順だと別商品が上に来やすい）
    format: "json",
    formatVersion: "2",
  });
  const res = await fetch(`${useLegacy ? RAKUTEN_API_URL_LEGACY : RAKUTEN_API_URL}?${params}`, {
    headers: {
      Origin: "https://camp-gear-lab.com",
      Referer: "https://camp-gear-lab.com/",
    },
  });
  if (!res.ok) {
    const body = await res.text().catch(() => "");
    if (body.includes("CLIENT_IP_NOT_ALLOWED") && !useLegacy) {
      useLegacy = true;
      console.warn(
        "  アクセスキーがIP制限で拒否（CLIENT_IP_NOT_ALLOWED）\n" +
          "  → https://webservice.rakuten.co.jp/ で現在のグローバルIP（curl -s ifconfig.me）を許可リストに追加してください"
      );
      return searchRakuten(keyword);
    }
    console.warn(`  API ${res.status}: ${keyword.slice(0, 30)}`);
    if (body) console.warn(`    応答: ${body.slice(0, 200)}`);
    return [];
  }
  const data = await res.json();
  return data.Items || [];
}

// サイズ違い誤マッチ防止: 商品名に単独のサイズ表記（S/M/L/XL・「2型」等）が
// ある場合、候補の商品名にも同じサイズが含まれることを必須にする。
// キーワードsanitizeで1文字トークンを落とすため、「アメニティドームL」の
// 検索結果にはMやSも混ざる。ここで弾かないと別サイズに誤リンクする
function sizeToken(name) {
  const m = name.match(/(?:^|[\s／/])([SML]|XL|LX|\d型)(?=$|[\s／/（(])/);
  return m ? m[1] : null;
}

function sizeMatches(productName, itemName) {
  const size = sizeToken(productName);
  if (!size) return true;
  const re = new RegExp(`(?:^|[\\s／/｜|（(【])${size}(?=$|[\\s／/｜|）)】])|(?:ドーム|テント|タープ|シェルター|サイズ)\\s?${size}(?![A-Za-z0-9])`);
  return re.test(itemName) || itemName.includes(` ${size} `) || itemName.endsWith(` ${size}`) || itemName.includes(`${size}サイズ`) || new RegExp(`[0-9ァ-ヶー一-龠]${size}(?![A-Za-z0-9])`).test(itemName);
}

// 価格ゲートは非対称にする。
// 下限は付属品・部品を掴む事故の防波堤なので厳しく保ち（0.6）、
// 上限は値上げ・円安で登録価格が古くなっている実態に合わせて緩める（2.0）。
// 中古を先に除外しているので、上限を緩めても転売価格は入りにくい。
const PRICE_MIN_RATIO = 0.6;
const PRICE_MAX_RATIO = 2.0;

function priceInRange(product, item) {
  if (!product.price) return true;
  return (
    item.itemPrice >= product.price * PRICE_MIN_RATIO &&
    item.itemPrice <= product.price * PRICE_MAX_RATIO
  );
}

function survivingCandidates(product, items) {
  return items.filter(
    (it) =>
      !USED_SHOP_PATTERNS.test(it.shopName || "") &&
      !USED_ITEM_PATTERNS.test(it.itemName || "") &&
      !isAccessoryMismatch(product.name, it.itemName || "") &&
      sizeMatches(product.name, it.itemName || "")
  );
}

function pickBest(product, items) {
  const models = modelNumbers(product.name);
  items = survivingCandidates(product, items);
  for (const item of items) {
    const itemModels = modelNumbers(item.itemName);
    const overlap = tokenOverlap(product.name, item.itemName);
    const priceOk = priceInRange(product, item);
    if (models.length > 0) {
      // 型番あり: 型番一致が必須。ただしカラー等の接尾辞は許す
      // （商品 BD-347 に対し 出品 BD-347BR は同一商品）
      if (models.some((m) => itemModels.some((im) => im === m || im.startsWith(m)))) {
        return { item, reason: `型番一致(${models[0]})`, overlap };
      }
    } else {
      // 型番なし: トークン一致70%以上 かつ 価格レンジ内
      if (overlap >= 0.7 && priceOk) {
        return { item, reason: `名称一致${Math.round(overlap * 100)}%+価格整合`, overlap };
      }
    }
  }
  return null;
}

// --explain 用。pickBest と同じゲートを再現し「どこで落ちたか」を返す。
// 判定には一切影響しない（採否は pickBest が単独で決める）
function diagnose(product, items) {
  if (items.length === 0) return { reason: "候補0件（検索がヒットしない）", top: null };

  const models = modelNumbers(product.name);
  const usedOut = items.filter(
    (it) => USED_SHOP_PATTERNS.test(it.shopName || "") || USED_ITEM_PATTERNS.test(it.itemName || "")
  );
  const accOut = items.filter(
    (it) =>
      !USED_SHOP_PATTERNS.test(it.shopName || "") &&
      !USED_ITEM_PATTERNS.test(it.itemName || "") &&
      isAccessoryMismatch(product.name, it.itemName || "")
  );
  const survivors = survivingCandidates(product, items);
  const sizeOut = items.length - usedOut.length - accOut.length - survivors.length;

  if (survivors.length === 0) {
    return {
      reason: `全候補が除外（中古${usedOut.length}・付属品${accOut.length}・サイズ不一致${sizeOut}）`,
      top: null,
      models,
      usedOut: usedOut.length,
      accOut: accOut.length,
      sizeOut,
    };
  }

  const scored = survivors
    .map((it) => {
      const overlap = tokenOverlap(product.name, it.itemName);
      const itemModels = modelNumbers(it.itemName);
      const modelHit =
        models.length > 0 &&
        models.some((m) => itemModels.some((im) => im === m || im.startsWith(m)));
      const priceOk = priceInRange(product, it);
      const ratio = product.price ? it.itemPrice / product.price : null;
      return { it, overlap, modelHit, priceOk, ratio };
    })
    .sort((a, b) => b.overlap - a.overlap);

  const top = scored[0];
  let reason;
  if (models.length > 0) {
    reason = "型番不一致（型番ありは完全一致が必須）";
  } else if (top.overlap < 0.7) {
    reason = `一致率不足（最高${Math.round(top.overlap * 100)}% < 70%）`;
  } else if (!scored.some((s) => s.overlap >= 0.7 && s.priceOk)) {
    reason = `価格乖離（一致率は足りたが登録価格の${Math.round(PRICE_MIN_RATIO * 100)}〜${Math.round(PRICE_MAX_RATIO * 100)}%外）`;
  } else {
    reason = "アフィリエイトURLが空";
  }
  return { reason, top, models, usedOut: usedOut.length, sizeOut, survivors: survivors.length };
}

function printDiagnosis(product, d) {
  console.log(`   └ 理由: ${d.reason}`);
  if (d.models?.length) console.log(`     商品側の型番: ${d.models.join(", ")}`);
  if (d.top) {
    const t = d.top;
    const price = product.price
      ? `¥${t.it.itemPrice.toLocaleString()}（登録¥${product.price.toLocaleString()} の ${Math.round(t.ratio * 100)}%）${t.priceOk ? "✓" : "✗"}`
      : `¥${t.it.itemPrice.toLocaleString()}（登録価格なし）`;
    console.log(`     最有力: ${t.it.itemName.slice(0, 50)}`);
    console.log(
      `     一致率${Math.round(t.overlap * 100)}% / 型番${t.modelHit ? "✓" : "✗"} / 価格 ${price}`
    );
    console.log(`     店舗: ${t.it.shopName}`);
  }
}

const products = JSON.parse(fs.readFileSync(PRODUCTS, "utf8"));
const targets = products.filter((p) => isSearchLink(p.affiliateUrl)).slice(0, LIMIT);
console.log(`検索ページ行きリンク: ${targets.length}件を処理（${APPLY ? "APPLY" : "dry-run"}）\n`);

const fixes = [];
const skipped = [];
for (const p of targets) {
  // キーワードを絞り込みが強い順に試し、採用できた時点で打ち切る。
  // 全部外れた場合は集めた候補をまとめて診断に回す
  const ladder = keywordLadder(p);
  let allItems = [];
  let best = null;
  let usedKeyword = null;
  for (const keyword of ladder) {
    await sleep(1100); // 楽天APIレート制限（1req/秒）
    const items = await searchRakuten(keyword);
    if (items.length > 0) allItems = allItems.concat(items);
    const candidate = pickBest(p, items);
    if (candidate && candidate.item.affiliateUrl) {
      best = candidate;
      usedKeyword = keyword;
      break;
    }
  }
  if (!best) {
    const d = diagnose(p, allItems);
    skipped.push({
      id: p.id,
      name: p.name,
      candidates: allItems.length,
      keywordsTried: ladder.length,
      reason: d.reason,
      topItemName: d.top?.it.itemName ?? null,
      topItemPrice: d.top?.it.itemPrice ?? null,
      productPrice: p.price ?? null,
      overlap: d.top ? Math.round(d.top.overlap * 100) : null,
    });
    console.log(
      `✗ スキップ: ${p.name.slice(0, 40)}（候補${allItems.length}件・キーワード${ladder.length}種試行・確信なし）`
    );
    if (EXPLAIN) printDiagnosis(p, d);
    continue;
  }
  fixes.push({
    id: p.id,
    name: p.name,
    reason: best.reason,
    keyword: usedKeyword,
    oldUrl: p.affiliateUrl,
    newUrl: best.item.affiliateUrl,
    itemName: best.item.itemName,
    itemPrice: best.item.itemPrice,
    shopName: best.item.shopName,
  });
  console.log(
    `✓ ${p.name.slice(0, 40)} → ${best.item.shopName}（${best.reason}）` +
      (EXPLAIN ? `\n   └ 採用キーワード: ${usedKeyword}` : "")
  );
  if (APPLY) {
    p.affiliateUrl = best.item.affiliateUrl;
  }
}

// スキップ理由の内訳。どのゲートが効いているかを一目で見るための集計
const reasonTally = {};
for (const s of skipped) {
  const key = (s.reason || "不明").replace(/（.*$/, "").trim();
  reasonTally[key] = (reasonTally[key] || 0) + 1;
}

fs.mkdirSync(path.dirname(REPORT), { recursive: true });
fs.writeFileSync(
  REPORT,
  JSON.stringify(
    { appliedAt: new Date().toISOString(), apply: APPLY, reasonTally, fixes, skipped },
    null,
    2
  )
);

if (skipped.length > 0) {
  console.log("\n── スキップ理由の内訳 ──");
  for (const [reason, n] of Object.entries(reasonTally).sort((a, b) => b[1] - a[1])) {
    console.log(`  ${String(n).padStart(3)}件  ${reason}`);
  }
  const priced = skipped.filter((s) => s.topItemPrice && s.productPrice);
  if (priced.length > 0) {
    const ratios = priced.map((s) => s.topItemPrice / s.productPrice).sort((a, b) => a - b);
    const median = ratios[Math.floor(ratios.length / 2)];
    console.log(
      `\n  参考: 最有力候補の実売 / 登録価格 の中央値 = ${Math.round(median * 100)}%（${priced.length}件で算出）`
    );
    console.log("  100%から大きく外れていれば、products.json の価格が古い可能性が高い");
  }
}
if (APPLY) {
  fs.writeFileSync(PRODUCTS, JSON.stringify(products, null, 2));
  console.log(`\nproducts.json 反映: ${fixes.length}件 / スキップ ${skipped.length}件`);
  console.log("次: git diff で確認 → コミット → sync（Supabase反映）");
} else {
  console.log(`\ndry-run完了: 提案${fixes.length}件 / スキップ${skipped.length}件 → ${REPORT}`);
  console.log("問題なければ --apply で反映してください");
}
