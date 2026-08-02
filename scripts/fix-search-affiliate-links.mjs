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
    .replace(/[×\/＋+|｜]/g, " ")
    .split(/\s+/)
    .filter((t) => [...t].length >= 2)
    .join(" ")
    .slice(0, 120);
}

// 中古・リユース店は除外（新品を勧める記事から中古在庫に飛ばさない）
const USED_SHOP_PATTERNS = /2nd STREET|セカンドストリート|ワットマン|リサイクル|中古|質屋|ブックオフ|BOOKOFF|トレファク|セカスト/i;

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

function pickBest(product, items) {
  const models = modelNumbers(product.name);
  items = items.filter(
    (it) =>
      !USED_SHOP_PATTERNS.test(it.shopName || "") &&
      sizeMatches(product.name, it.itemName || "")
  );
  for (const item of items) {
    const itemModels = modelNumbers(item.itemName);
    const overlap = tokenOverlap(product.name, item.itemName);
    const priceOk =
      !product.price ||
      (item.itemPrice >= product.price * 0.6 &&
        item.itemPrice <= product.price * 1.4);
    if (models.length > 0) {
      // 型番あり: 型番一致が必須。価格は参考（型番が合えば多少の乖離は許容）
      if (models.some((m) => itemModels.includes(m))) {
        return { item, reason: `型番一致(${models[0]})`, overlap };
      }
    } else {
      // 型番なし: トークン一致70%以上 かつ 価格±40%以内
      if (overlap >= 0.7 && priceOk) {
        return { item, reason: `名称一致${Math.round(overlap * 100)}%+価格整合`, overlap };
      }
    }
  }
  return null;
}

const products = JSON.parse(fs.readFileSync(PRODUCTS, "utf8"));
const targets = products.filter((p) => isSearchLink(p.affiliateUrl)).slice(0, LIMIT);
console.log(`検索ページ行きリンク: ${targets.length}件を処理（${APPLY ? "APPLY" : "dry-run"}）\n`);

const fixes = [];
const skipped = [];
for (const p of targets) {
  await sleep(1100); // 楽天APIレート制限（1req/秒）
  const brand = p.brand && !p.name.includes(p.brand) ? `${p.brand} ` : "";
  const items = await searchRakuten(`${brand}${p.name}`);
  let best = pickBest(p, items);
  // フォールバック: 商品名フルでヒットしない場合、型番だけで再検索
  // （店の商品名は語順・表記が違うことが多く、型番検索の方が刺さる）
  if (!best) {
    const models = p.name.match(/[A-Za-z]{1,6}-[A-Za-z0-9]{2,10}|[A-Za-z]{2,6}[0-9]{2,5}[A-Za-z0-9]*/g);
    if (models && models.length > 0) {
      await sleep(1100);
      const brandWord = (p.brand || p.name.split(/\s+/)[0] || "").slice(0, 20);
      const retry = await searchRakuten(`${brandWord} ${models[0]}`);
      best = pickBest(p, retry);
    }
  }
  if (!best || !best.item.affiliateUrl) {
    skipped.push({ id: p.id, name: p.name, candidates: items.length });
    console.log(`✗ スキップ: ${p.name.slice(0, 40)}（候補${items.length}件・確信なし）`);
    continue;
  }
  fixes.push({
    id: p.id,
    name: p.name,
    reason: best.reason,
    oldUrl: p.affiliateUrl,
    newUrl: best.item.affiliateUrl,
    itemName: best.item.itemName,
    itemPrice: best.item.itemPrice,
    shopName: best.item.shopName,
  });
  console.log(`✓ ${p.name.slice(0, 40)} → ${best.item.shopName}（${best.reason}）`);
  if (APPLY) {
    p.affiliateUrl = best.item.affiliateUrl;
  }
}

fs.mkdirSync(path.dirname(REPORT), { recursive: true });
fs.writeFileSync(REPORT, JSON.stringify({ appliedAt: new Date().toISOString(), apply: APPLY, fixes, skipped }, null, 2));
if (APPLY) {
  fs.writeFileSync(PRODUCTS, JSON.stringify(products, null, 2));
  console.log(`\nproducts.json 反映: ${fixes.length}件 / スキップ ${skipped.length}件`);
  console.log("次: git diff で確認 → コミット → sync（Supabase反映）");
} else {
  console.log(`\ndry-run完了: 提案${fixes.length}件 / スキップ${skipped.length}件 → ${REPORT}`);
  console.log("問題なければ --apply で反映してください");
}
