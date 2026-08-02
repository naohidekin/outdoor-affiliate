#!/usr/bin/env node
/**
 * 秋冬2026 P1「冬の暖房エース記事」用の商品データ整備
 *
 * 背景: docs/fall-winter-2026-plan.md の P1（石油 vs 薪 vs ガス vs 電気の全方式比較）を
 * 書くには、現状の在庫（石油3台＋COチェッカー3台）では方式が埋まらない。
 * 薪・ガス・電気の代表機と、目玉のコロナ FH-CPF25A を追加する。
 *
 * 楽天Ichiba APIで実商品を引き当て、価格・画像・アフィリエイトURLを自動取得する。
 * スペックと説明文は事前調査済みの内容を使う（APIの商品名は店舗の装飾が多く使えないため）。
 *
 * 使い方（Mac・要 RAKUTEN_APP_ID / RAKUTEN_ACCESS_KEY）:
 *   node scripts/add-winter-heating-products.mjs            # dry-run（提案のみ）
 *   node scripts/add-winter-heating-products.mjs --apply    # products.jsonへ追記
 *
 * 安全装置:
 * - mustMatch（型番・ブランド語）が候補の商品名に含まれない限り採用しない
 * - 中古・リユース店は除外
 * - 既に同じidの商品があればスキップ（再実行しても重複しない）
 * - dry-runがデフォルト。--apply でも scratch/ に全提案を記録
 *
 * amazonUrl は付かない（ASINは楽天APIから取れない）。記事掲載前に
 * Amazon商品ページの /dp/ 以降10桁を手で入れること。
 */
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const ROOT = path.join(__dirname, "..");
const PRODUCTS = path.join(ROOT, "data", "products.json");
const REPORT = path.join(ROOT, "scratch", "winter-heating-products.json");

const RAKUTEN_API_URL =
  "https://openapi.rakuten.co.jp/ichibams/api/IchibaItem/Search/20220601";
const RAKUTEN_AFFILIATE_ID =
  process.env.RAKUTEN_AFFILIATE_ID || "18eb3228.621d8df3.18eb3229.ec5f8d49";

const APPLY = process.argv.includes("--apply");
const appId = process.env.RAKUTEN_APP_ID;
const accessKey = process.env.RAKUTEN_ACCESS_KEY;
if (!appId || !accessKey) {
  console.error("RAKUTEN_APP_ID / RAKUTEN_ACCESS_KEY が未設定です");
  process.exit(1);
}

// ─── 追加候補 ────────────────────────────────────────
// specs / description は事前調査（メーカー公式・専門メディア）に基づく確定値。
// price / imageUrl / affiliateUrl は楽天APIの実データで埋める。
const CANDIDATES = [
  // ── 石油（ポータブル電源対応・P1の目玉） ──
  {
    id: "heater-corona-fh-cpf25a",
    name: "コロナ OUTFIELD ポータブル電源対応石油ファンヒーター FH-CPF25A",
    brand: "コロナ",
    keyword: "コロナ OUTFIELD 石油ファンヒーター FH-CPF25A",
    mustMatch: ["FH-CPF25A", "FHCPF25A"],
    specs: {
      暖房出力: "2.5kW",
      消費電力: "8.5〜14W（運転時）",
      連続燃焼: "540Whのポータブル電源で約27時間",
      高地対応: "標高2,000mまで（高地設定モード）",
      安全装置: "対震自動消火・不完全燃焼防止",
    },
    description:
      "消費電力8.5〜14Wという圧倒的な省電力で、540Whクラスのポータブル電源でも一晩まわせる石油ファンヒーター。標高2,000mまでの高地設定モードと水平器を搭載し、電源サイト以外の冬キャンプでも使えます。",
  },
  // ── 薪 ──
  {
    id: "heater-winnerwell-nomad-view-m",
    name: "Winnerwell Nomad View M 薪ストーブ",
    brand: "Winnerwell",
    keyword: "Winnerwell ウィンナーウェル Nomad View 薪ストーブ M",
    mustMatch: ["Nomad", "ノマド"],
    specs: {
      素材: "ステンレス（SUS304）",
      窓: "耐熱ガラス窓付き",
      形式: "テント内設営前提の煙突式",
      拡張性: "オプションパーツが豊富",
    },
    description:
      "ステンレス製薪ストーブの世界的定番。錆びにくく手入れがしやすい作りで、煙突・オプションの選択肢が広いのが強みです。ガラス窓から炎が見えるので、暖房と焚き火の楽しさを両立できます。",
  },
  {
    id: "heater-mtsumi-midora",
    name: "Mt.SUMI ミドラ 薪ストーブ",
    brand: "Mt.SUMI",
    keyword: "Mt.SUMI マウントスミ ミドラ 薪ストーブ",
    mustMatch: ["ミドラ", "MIDORA", "Midora"],
    specs: {
      窓: "正面＋両サイドの3面大型ガラス",
      燃焼: "二次燃焼構造",
      薪長: "40cmの薪がそのまま入る",
      サイズ感: "ミドルサイズ",
    },
    description:
      "3面ガラスで炎がよく見えるミドルサイズの薪ストーブ。二次燃焼構造で燃焼効率が高く、40cmの薪を割らずに入れられる実用性も持っています。見た目と実用のバランスがいい一台です。",
  },
  {
    id: "heater-vastland-wood-stove",
    name: "VASTLAND 薪ストーブ",
    brand: "VASTLAND",
    keyword: "VASTLAND 薪ストーブ キャンプ 煙突",
    mustMatch: ["VASTLAND", "ヴァストランド"],
    specs: {
      価格帯: "エントリー",
      形式: "煙突式・折りたたみ脚",
      用途: "薪ストーブ入門",
    },
    description:
      "薪ストーブを試してみたい人向けの国内ブランドのエントリーモデル。まず一冬使ってみて、自分のスタイルに合うか確かめるのに向いています。",
  },
  // ── ガス ──
  {
    id: "heater-iwatani-dekadan3",
    name: "イワタニ カセットガスストーブ デカ暖III CB-STV-DKD3",
    brand: "イワタニ",
    keyword: "イワタニ カセットガスストーブ デカ暖3 CB-STV-DKD3",
    mustMatch: ["DKD3", "デカ暖3", "デカ暖III", "デカ暖Ⅲ"],
    specs: {
      燃料: "カセットガス（CB缶）",
      構造: "セラミック筒・パンチングメタル筒・ステンレスメッシュ筒の3層",
      給排気: "屋外・換気必須",
      利点: "灯油不要で扱いが手軽",
    },
    description:
      "CB缶1本で使えるカセットガスストーブの最新モデル。灯油の給油やニオイがなく、冬キャンプの暖房として一番手を出しやすい方式です。持続時間の短さと引き換えの手軽さと考えてください。",
  },
  {
    id: "heater-iwatani-kazedan",
    name: "イワタニ カセットガスファンヒーター 風暖",
    brand: "イワタニ",
    keyword: "イワタニ カセットガスファンヒーター 風暖",
    mustMatch: ["風暖"],
    specs: {
      燃料: "カセットガス（CB缶）",
      形式: "ファンヒーター（温風）",
      電源: "乾電池（点火・送風用）",
      利点: "電源不要で温風が出せる",
    },
    description:
      "CB缶と乾電池だけで温風が出せるガスファンヒーター。コンセントもポータブル電源も不要で、電源サイト以外でも温風暖房ができるのが最大の強みです。",
  },
  // ── 電気（電気毛布はP2記事の主役でもある） ──
  {
    id: "heater-koizumi-electric-blanket",
    name: "コイズミ 電気敷毛布",
    brand: "コイズミ",
    keyword: "コイズミ 電気敷毛布 洗える",
    mustMatch: ["コイズミ", "KOIZUMI"],
    specs: {
      消費電力: "約40W",
      形式: "敷きタイプ",
      手入れ: "丸洗い可（モデルによる）",
      電源目安: "500Whクラスのポータブル電源で一晩",
    },
    description:
      "消費電力40W前後の省エネ敷き毛布。500Whクラスのポータブル電源でも朝まで持つので、電源なしサイトの冬キャンプで一番費用対効果が高い暖房です。シュラフの中に敷いて使います。",
  },
  {
    id: "heater-yamazen-electric-blanket",
    name: "山善 電気毛布",
    brand: "山善",
    keyword: "山善 電気毛布 敷き 洗える",
    mustMatch: ["山善", "YAMAZEN"],
    specs: {
      消費電力: "約40〜55W",
      形式: "敷きタイプ",
      手入れ: "丸洗い可（モデルによる）",
      価格帯: "エントリー",
    },
    description:
      "キャンプ用電気毛布の定番格。価格が手ごろで、まず1枚試すのに向いています。ポータブル電源の容量計算がしやすい消費電力表示も助かります。",
  },
];

const USED_SHOP_PATTERNS =
  /2nd STREET|セカンドストリート|ワットマン|リサイクル|中古|質屋|ブックオフ|BOOKOFF|トレファク|セカスト/i;

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

// 楽天APIは1文字の単語を含むキーワードを400で弾く
function sanitizeKeyword(s) {
  return s
    .replace(/[×\/＋+|｜]/g, " ")
    .split(/\s+/)
    .filter((t) => [...t].length >= 2)
    .join(" ")
    .slice(0, 120);
}

// パラメータは実績のある fix-search-affiliate-links.mjs と同一に揃える
// （hits=20 / imageFlag などを足すと差分要因が増えるため最小構成）
// アクセスキーはIP許可リストで縛られており、グローバルIPが変わると
// CLIENT_IP_NOT_ALLOWED で全滅する。アクセスキーは任意項目なので、
// 弾かれたら applicationId のみで再試行する（アフィリURLはaffiliateIdで付く）
let useAccessKey = true;

async function searchRakuten(keyword, attempt = 0) {
  const params = new URLSearchParams({
    applicationId: appId,
    ...(useAccessKey ? { accessKey } : {}),
    affiliateId: RAKUTEN_AFFILIATE_ID,
    keyword: sanitizeKeyword(keyword),
    hits: "10",
    sort: "standard",
    formatVersion: "2",
  });
  const res = await fetch(`${RAKUTEN_API_URL}?${params}`, {
    headers: {
      Origin: "https://camp-gear-lab.com",
      Referer: "https://camp-gear-lab.com/",
    },
  });
  if (!res.ok) {
    const body = await res.text().catch(() => "");
    // アクセスキーのIP制限で弾かれた → 以降はアクセスキー無しで叩く
    if (body.includes("CLIENT_IP_NOT_ALLOWED") && useAccessKey) {
      useAccessKey = false;
      console.warn(
        "  アクセスキーがIP制限で拒否されました → applicationIdのみで再試行します"
      );
      return searchRakuten(keyword, attempt);
    }
    // 429などのレート制限は間隔を空けて1度だけ再試行する
    if (res.status === 429 && attempt < 1) {
      console.warn(`  API ${res.status} → 20秒待って再試行: ${keyword}`);
      await sleep(20000);
      return searchRakuten(keyword, attempt + 1);
    }
    console.warn(`  API ${res.status}: ${keyword}`);
    if (body) console.warn(`    応答: ${body.slice(0, 300)}`);
    return [];
  }
  const data = await res.json();
  return data.Items || [];
}

function pickBest(cand, items) {
  const norm = (s) => (s || "").toUpperCase().replace(/[\s　-]/g, "");
  return (
    items
      .filter((it) => !USED_SHOP_PATTERNS.test(it.shopName || ""))
      .filter((it) => it.affiliateUrl && it.itemPrice > 0)
      // mustMatchのどれかが商品名に含まれることを必須にする
      .find((it) =>
        cand.mustMatch.some((m) => norm(it.itemName).includes(norm(m)))
      ) || null
  );
}

const products = JSON.parse(fs.readFileSync(PRODUCTS, "utf8"));
const existing = new Set(products.map((p) => p.id));
const now = new Date().toISOString();

console.log(
  `冬の暖房 商品追加: 候補${CANDIDATES.length}件（${APPLY ? "APPLY" : "dry-run"}）\n`
);

const added = [];
const skipped = [];
for (const cand of CANDIDATES) {
  if (existing.has(cand.id)) {
    console.log(`− 既存のためスキップ: ${cand.name}`);
    continue;
  }
  await sleep(2000); // 楽天APIのレート制限に余裕を持たせる
  const items = await searchRakuten(cand.keyword);
  const best = pickBest(cand, items);
  if (!best) {
    skipped.push({ id: cand.id, name: cand.name, candidates: items.length });
    console.log(`✗ 見つからず: ${cand.name}（候補${items.length}件）`);
    continue;
  }
  const entry = {
    id: cand.id,
    name: cand.name,
    brand: cand.brand,
    price: best.itemPrice,
    imageUrl: (best.mediumImageUrls && best.mediumImageUrls[0]) || "",
    affiliateUrl: best.affiliateUrl,
    amazonUrl: "",
    categoryId: "heater",
    specs: cand.specs,
    description: cand.description,
    rating: Number(best.reviewAverage) || 0,
    priceUpdatedAt: now,
    createdAt: now,
    updatedAt: now,
  };
  added.push({ entry, source: { itemName: best.itemName, shop: best.shopName } });
  console.log(
    `✓ ${cand.name}\n    ¥${best.itemPrice.toLocaleString()} / ${best.shopName} / ★${best.reviewAverage || "-"}（${best.reviewCount || 0}件）\n    ${best.itemName.slice(0, 60)}`
  );
  if (APPLY) products.push(entry);
}

fs.mkdirSync(path.dirname(REPORT), { recursive: true });
fs.writeFileSync(
  REPORT,
  JSON.stringify({ ranAt: now, apply: APPLY, added, skipped }, null, 2)
);
if (APPLY) {
  fs.writeFileSync(PRODUCTS, JSON.stringify(products, null, 2));
  console.log(`\nproducts.json 追記: ${added.length}件 / 見つからず ${skipped.length}件`);
  console.log("次: git diff で確認 → コミット → sync（--no-pull 推奨）");
} else {
  console.log(`\ndry-run完了: 提案${added.length}件 / 見つからず${skipped.length}件 → ${REPORT}`);
  console.log("問題なければ --apply で反映してください");
}
