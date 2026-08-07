#!/usr/bin/env node
/**
 * Amazon検索ページ行きリンクの商品直リンク化
 *
 * 背景（2026-08-05調査）: products.json の amazonUrl のうち77件が
 * 「https://www.amazon.co.jp/s?k=...」という検索結果ページへのリンクだった。
 * 楽天側で同じ構造の問題（コロナ PA-F85A が511クリックで成果ゼロ）が
 * 判明したのと同根で、検索結果に着地した読者は迷子になり成約しない。
 *
 * 混入時期を追うと、壊れ率は 2026-04:14% → 06:28% → 07:76% と上昇していた。
 * PA-API v5 が段階的に停止（OffersV2は1月末、本体は5/15）した結果、
 * ASINを取得できずフォールバックの検索URLが入り続けたのが原因。
 *
 * このスクリプトは Creators API の searchItems で実商品を探し、
 * /dp/{ASIN}/?tag=... 形式の直リンクに置き換える。
 * 判定ロジックは楽天版で実測調整したものを src/lib/product-match.mjs から使う。
 *
 * 使い方（Macで実行。Creators API 認証情報が必要）:
 *   node scripts/fix-amazon-search-links.mjs                    # dry-run
 *   node scripts/fix-amazon-search-links.mjs --explain          # 判定内訳つき
 *   node scripts/fix-amazon-search-links.mjs --apply            # 高・中のみ反映
 *   node scripts/fix-amazon-search-links.mjs --apply --only id1,id2
 *   node scripts/fix-amazon-search-links.mjs --limit 10
 *   node scripts/fix-amazon-search-links.mjs --missing-only     # amazonUrl未設定のみ
 *   node scripts/fix-amazon-search-links.mjs --include-missing  # 検索URL＋未設定
 *   node scripts/fix-amazon-search-links.mjs --ids id1,id2      # ID指定で調べ直す
 *
 * --ids と --only は別物:
 *   --ids  … 調べる商品を指定（既に /dp/ が入っていても対象にする）
 *   --only … 調べた結果のうち反映する商品を指定（低でも反映する）
 *
 * 信頼度（--apply は既定で 高・中 のみ）:
 *   高 … 型番一致  中 … 商品名フル検索で一致率100%  低 … 要目視
 *
 * 反映後は同期が必要。--no-pull を必ず付ける:
 *   npm run db:sync -- --no-pull
 */
import fs from "node:fs";
import path from "node:path";
import dns from "node:dns";
import { fileURLToPath } from "node:url";
import { loadEnv } from "../src/lib/x-agent-utils.mjs";
import { creatorsApi, credentials, hasCredentials } from "../src/lib/amazon-creators-api.mjs";
import {
  keywordLadder,
  generationMismatch,
  isShortenedKeyword,
  confidenceTier,
  pickBest,
  survivingCandidates,
  tokenOverlap,
  modelNumbers,
  priceInRange,
  USED_ITEM_PATTERNS,
  isAccessoryMismatch,
  sizeMatches,
  PRICE_MIN_RATIO,
  PRICE_MAX_RATIO,
} from "../src/lib/product-match.mjs";

// IPv6回線での接続差異を避ける（楽天のIP制限で実害が出たため揃えておく）
dns.setDefaultResultOrder("ipv4first");
loadEnv();

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const ROOT = path.join(__dirname, "..");
const PRODUCTS = path.join(ROOT, "data", "products.json");
const REPORT = path.join(ROOT, "scratch", "amazon-link-fixes.json");

const argv = process.argv.slice(2);
const APPLY = argv.includes("--apply");
const WITH_LOW = argv.includes("--with-low");
const EXPLAIN = argv.includes("--explain");
const argVal = (name) => {
  const i = argv.indexOf(name);
  return i !== -1 && argv[i + 1] ? argv[i + 1] : null;
};
const ONLY = new Set((argVal("--only") || "").split(",").map((s) => s.trim()).filter(Boolean));
// --only は「適用する商品」の指定であって、調べる商品の指定ではない。
// 既に /dp/ リンクが入っているが中身が別商品、というケース（ツーリングドームLXが
// STのASINを指す等）は通常の対象条件に入らないので、IDで直接呼び出せるようにする
const IDS = new Set((argVal("--ids") || "").split(",").map((s) => s.trim()).filter(Boolean));
// amazonUrl が空の商品も対象にする。買う導線がゼロなので検索URLより優先度が高い
const INCLUDE_MISSING = argv.includes("--include-missing");
const MISSING_ONLY = argv.includes("--missing-only");
const LIMIT = parseInt(argVal("--limit") || "", 10) || Infinity;

if (!hasCredentials()) {
  console.error(
    "Creators API認証情報がありません（.env.local の AMAZON_CREDENTIAL_ID / AMAZON_CREDENTIAL_SECRET）"
  );
  process.exit(1);
}

const PARTNER_TAG = credentials().partnerTag;
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

let authFailures = 0;
const AUTH_FAILURE_LIMIT = 5;

/** 検索ページ行きのAmazonリンクか */
function isSearchLink(url) {
  return /amazon\.co\.jp\/s\?/.test(url || "");
}

/** amazonUrl が空＝Amazonで買う導線が無い。検索URLより実害が大きい */
function isMissingLink(url) {
  return !url || !String(url).trim();
}

function asinOf(url) {
  const m = (url || "").match(/\/(?:dp|gp\/product)\/([A-Z0-9]{10})/i);
  return m ? m[1].toUpperCase() : null;
}

async function searchAmazon(keywords) {
  try {
    const data = await creatorsApi("/catalog/v1/searchItems", {
      keywords: keywords.slice(0, 100),
      searchIndex: "All",
      itemCount: 10,
      partnerTag: PARTNER_TAG,
      resources: ["itemInfo.title", "offersV2.listings.price"],
    });
    authFailures = 0;
    // 共通の照合ロジックが期待する形（title / price）に正規化する
    return (data.searchResult?.items || []).map((it) => ({
      asin: it.asin,
      title: it.itemInfo?.title?.displayValue || "",
      price: it.offersV2?.listings?.[0]?.price?.money?.amount ?? null,
    }));
  } catch (e) {
    const msg = String(e.message);
    console.warn(`  API失敗: ${keywords.slice(0, 34)}`);
    console.warn(`    ${msg.slice(0, 160)}`);
    // 認証・権限まわりが続くなら設定の問題。77件回し切る前に止める
    if (/401|403|トークン取得失敗|Unauthorized|AccessDenied/i.test(msg)) {
      if (++authFailures >= AUTH_FAILURE_LIMIT) {
        console.error(
          `\n認証エラーが${AUTH_FAILURE_LIMIT}回続きました。設定を確認してから再実行してください。\n` +
            "  ・.env.local の AMAZON_CREDENTIAL_ID / AMAZON_CREDENTIAL_SECRET がペアか\n" +
            "  ・アソシエイト・セントラルで認証情報がACTIVEか\n" +
            "  ・PA APIアクセスには過去30日で10件以上の売上が必要\n"
        );
        process.exit(1);
      }
    }
    return [];
  }
}

// ─── 診断（--explain 用。判定には影響しない） ──────────────
function diagnose(product, items) {
  if (items.length === 0) return { reason: "候補0件（検索がヒットしない）", top: null };

  const models = modelNumbers(product.name);
  const usedOut = items.filter((it) => USED_ITEM_PATTERNS.test(it.title || ""));
  const accOut = items.filter(
    (it) => !USED_ITEM_PATTERNS.test(it.title || "") && isAccessoryMismatch(product.name, it.title || "")
  );
  const survivors = survivingCandidates(product, items);
  const sizeOut = items.length - usedOut.length - accOut.length - survivors.length;

  if (survivors.length === 0) {
    return {
      reason: `全候補が除外（中古${usedOut.length}・付属品${accOut.length}・サイズ不一致${sizeOut}）`,
      top: null,
      models,
    };
  }

  const scored = survivors
    .map((it) => {
      const overlap = tokenOverlap(product.name, it.title || "");
      const itemModels = modelNumbers(it.title || "");
      const modelHit =
        models.length > 0 && models.some((m) => itemModels.some((im) => im === m || im.startsWith(m)));
      return { it, overlap, modelHit, priceOk: priceInRange(product.price, it.price) };
    })
    .sort((a, b) => b.overlap - a.overlap);

  const top = scored[0];
  let reason;
  if (models.length > 0) reason = "型番不一致（型番ありは完全一致が必須）";
  else if (top.overlap < 0.7) reason = `一致率不足（最高${Math.round(top.overlap * 100)}% < 70%）`;
  else if (!scored.some((s) => s.overlap >= 0.7 && s.priceOk))
    reason = `価格乖離（登録価格の${Math.round(PRICE_MIN_RATIO * 100)}〜${Math.round(PRICE_MAX_RATIO * 100)}%外）`;
  else reason = "ASINが取得できない";
  return { reason, top, models };
}

function printDiagnosis(product, d) {
  console.log(`   └ 理由: ${d.reason}`);
  if (d.models?.length) console.log(`     商品側の型番: ${d.models.join(", ")}`);
  if (d.top) {
    const t = d.top;
    const price = product.price
      ? `¥${(t.it.price ?? 0).toLocaleString()}（登録¥${product.price.toLocaleString()} の ${
          t.it.price ? Math.round((t.it.price / product.price) * 100) : "?"
        }%）${t.priceOk ? "✓" : "✗"}`
      : `¥${(t.it.price ?? 0).toLocaleString()}`;
    console.log(`     最有力: ${t.it.title.slice(0, 54)}`);
    console.log(`     一致率${Math.round(t.overlap * 100)}% / 型番${t.modelHit ? "✓" : "✗"} / ${price}`);
    console.log(`     ASIN: ${t.it.asin}`);
  }
}

// ─── 本処理 ──────────────────────────────────────────
const products = JSON.parse(fs.readFileSync(PRODUCTS, "utf8"));
const pickTarget = (p) => {
  if (IDS.size > 0) return IDS.has(p.id);
  if (MISSING_ONLY) return isMissingLink(p.amazonUrl);
  if (INCLUDE_MISSING) return isSearchLink(p.amazonUrl) || isMissingLink(p.amazonUrl);
  return isSearchLink(p.amazonUrl);
};
const targets = products.filter(pickTarget).slice(0, LIMIT);

// 既に他の商品が使っているASIN。汎用的な商品名（「軽量折りたたみアウトドアチェア」
// 「クーラーボックス」等）は同じASINへ収束しやすく、複数商品が同一ページを
// 指してしまう。2026-08-06 に B0H4QWP4K3 が2商品に付く事例を確認した
const asinOwner = new Map();
for (const p of products) {
  const a = asinOf(p.amazonUrl);
  if (a && !asinOwner.has(a)) asinOwner.set(a, p.id);
}

const scope = IDS.size > 0
  ? "ID指定"
  : MISSING_ONLY
    ? "amazonUrl未設定"
    : INCLUDE_MISSING
      ? "検索ページ行き＋未設定"
      : "検索ページ行き";
console.log(`Amazon ${scope}: ${targets.length}件を処理（${APPLY ? "APPLY" : "dry-run"}）\n`);

const fixes = [];
const skipped = [];

for (const p of targets) {
  // Amazonには楽天のような1文字語の制約が無い。世代番号（WAVE 2 の 2）を残す
  const ladder = keywordLadder(p, { minTokenLength: 1 });
  let allItems = [];
  let best = null;
  let usedKeyword = null;

  for (const keyword of ladder) {
    await sleep(1200); // Creators APIのレート制限に配慮
    const items = await searchAmazon(keyword);
    if (items.length > 0) allItems = allItems.concat(items);
    const candidate = pickBest(p, items);
    if (candidate?.item?.asin) {
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
      topTitle: d.top?.it.title ?? null,
      topAsin: d.top?.it.asin ?? null,
      topPrice: d.top?.it.price ?? null,
      productPrice: p.price ?? null,
    });
    console.log(
      `✗ スキップ: ${p.name.slice(0, 38)}（候補${allItems.length}件・キーワード${ladder.length}種試行）`
    );
    if (EXPLAIN) printDiagnosis(p, d);
    continue;
  }

  const shortened = isShortenedKeyword(p.name, usedKeyword);
  let tier = confidenceTier(best.reason, best.overlap, shortened);
  const newUrl = `https://www.amazon.co.jp/dp/${best.item.asin}/?tag=${PARTNER_TAG}`;

  // 他の商品が既に使っているASINなら、どちらかが誤り。自動適用はしない
  const dupOwner = asinOwner.get(best.item.asin);
  const duplicate = dupOwner && dupOwner !== p.id;
  if (duplicate) tier = "低";

  // 商品名の数字が候補に無い＝世代・容量違いの疑い。自動適用はしない
  const genMismatch = generationMismatch(p.name, best.item.title || "");
  if (genMismatch) tier = "低";

  fixes.push({
    id: p.id,
    name: p.name,
    tier,
    reason: best.reason,
    keyword: usedKeyword,
    keywordShortened: shortened,
    overlap: Math.round(best.overlap * 100),
    asin: best.item.asin,
    oldUrl: p.amazonUrl,
    newUrl,
    itemTitle: best.item.title,
    itemPrice: best.item.price,
    productPrice: p.price ?? null,
    duplicateOf: duplicate ? dupOwner : null,
    generationMismatch: genMismatch,
  });

  console.log(`✓[${tier}] ${p.name.slice(0, 36)} → ${best.item.asin}（${best.reason}）`);
  if (duplicate) console.log(`   ⚠ ASIN重複: ${dupOwner} が既に使用中。どちらかが誤り`);
  if (genMismatch) console.log("   ⚠ 商品名の数字が候補に無い。世代・容量違いの疑い");
  if (EXPLAIN || tier === "低") console.log(`   └ 採用キーワード: ${usedKeyword}`);
}

const byTier = { 高: [], 中: [], 低: [] };
for (const f of fixes) byTier[f.tier].push(f);

const wouldApply = (f) => (ONLY.size > 0 ? ONLY.has(f.id) : f.tier !== "低" || WITH_LOW);

if (APPLY) {
  const ts = new Date().toISOString();
  for (const f of fixes) {
    if (!wouldApply(f)) continue;
    const p = products.find((q) => q.id === f.id);
    if (!p) continue;
    // 同一実行の中でも同じASINを2商品に付けない
    const owner = asinOwner.get(f.asin);
    if (owner && owner !== f.id) {
      console.log(`⚠ 適用しない: ${f.id} … ASIN ${f.asin} は ${owner} が使用中`);
      continue;
    }
    asinOwner.set(f.asin, f.id);
    p.amazonUrl = f.newUrl;
    // updatedAt を進めないと sync の auto-pull で旧URLに巻き戻る
    p.updatedAt = ts;
    f.applied = true;
  }
}

fs.mkdirSync(path.dirname(REPORT), { recursive: true });
fs.writeFileSync(
  REPORT,
  JSON.stringify(
    {
      checkedAt: new Date().toISOString(),
      apply: APPLY,
      withLow: WITH_LOW,
      tierCounts: { 高: byTier.高.length, 中: byTier.中.length, 低: byTier.低.length },
      fixes,
      skipped,
    },
    null,
    2
  )
);

if (skipped.length > 0) {
  const tally = {};
  for (const s of skipped) {
    const key = (s.reason || "不明").replace(/（.*$/, "").trim();
    tally[key] = (tally[key] || 0) + 1;
  }
  console.log("\n── スキップ理由の内訳 ──");
  for (const [reason, n] of Object.entries(tally).sort((a, b) => b[1] - a[1])) {
    console.log(`  ${String(n).padStart(3)}件  ${reason}`);
  }
}

if (fixes.length > 0) {
  console.log("\n── 信頼度の内訳 ──");
  console.log(`  高 ${String(byTier.高.length).padStart(3)}件  型番一致`);
  console.log(`  中 ${String(byTier.中.length).padStart(3)}件  商品名フル検索で一致率100%`);
  console.log(`  低 ${String(byTier.低.length).padStart(3)}件  一致率100%未満／短縮／世代違いの疑い`);

  if (byTier.低.length > 0) {
    console.log("\n── 要目視（低）──");
    console.log("  別サイズ・別グレード・付属品を掴んでいないか確認してください\n");
    for (const f of byTier.低) {
      const priceNote = f.productPrice && f.itemPrice
        ? `¥${f.itemPrice.toLocaleString()}（登録¥${f.productPrice.toLocaleString()} の ${Math.round((f.itemPrice / f.productPrice) * 100)}%）`
        : `¥${(f.itemPrice ?? 0).toLocaleString()}`;
      console.log(`  ${f.id}  ${f.name.slice(0, 34)}`);
      console.log(`    → ${f.itemTitle.slice(0, 54)}`);
      console.log(`    一致率${f.overlap}% / ${f.keywordShortened ? "キーワード短縮" : "フル検索"} / ${priceNote}`);
      if (f.duplicateOf) console.log(`    ⚠ ASIN重複: ${f.duplicateOf} と同じ商品を指している`);
      if (f.generationMismatch) console.log("    ⚠ 商品名の数字が候補に無い。世代・容量違いの疑い");
      console.log(`    ${f.newUrl}\n`);
    }
  }
}

const applyCount = fixes.filter(wouldApply).length;

if (APPLY) {
  fs.writeFileSync(PRODUCTS, JSON.stringify(products, null, 2));
  const note =
    ONLY.size > 0
      ? `--only 指定の${applyCount}件`
      : `高${byTier.高.length} 中${byTier.中.length}` +
        (WITH_LOW ? ` 低${byTier.低.length}` : ` / 低${byTier.低.length}件は未適用`);
  console.log(`\nproducts.json 反映: ${applyCount}件（${note}）`);
  console.log("次: git diff で確認 → npm run db:sync -- --no-pull");
} else {
  console.log(`\ndry-run完了: 提案${fixes.length}件（適用対象${applyCount}件）/ スキップ${skipped.length}件`);
  console.log(`レポート: ${REPORT}`);
  console.log("適用: --apply                  … 高・中のみ");
  console.log("      --apply --only id1,id2  … 目視した商品だけ（低も反映）");
  console.log("調査: --ids id1,id2            … 既存リンクの正誤を調べ直す");
}
