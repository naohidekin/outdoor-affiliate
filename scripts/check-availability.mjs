#!/usr/bin/env node
/**
 * 商品が「まだ買えるか」を確認する（廃番・終売チェック）
 *
 * 背景（2026-08-06）: 楽天リンクの修正作業中に、候補が中古しか無い商品や
 * 別サイズしか無い商品が複数見つかった。
 *   タフスクリーンタープ/400・400+ / キッズマミー C4 / GSIケトル /
 *   ネイチャーハイク CW280 … いずれも楽天は中古のみ
 *   アメニティドームL は M/S のみ、REVOタープ II M は L のみ
 * 記事で「おすすめ」として紹介し続けていても読者は買えない。
 * リンクの精度より影響が大きいので、状態を可視化する。
 *
 * Amazon の在庫は Creators API の getItems で判定する（link-fix.mjs と同じ規則）:
 *   itemsResult に居てオファーあり  → 販売中
 *   itemsResult に居るがオファー無し → 取扱終了
 *   errors で ItemNotAccessible 等   → ASIN消滅
 *
 * 楽天側は fix-search-affiliate-links の実行結果
 * （scratch/affiliate-link-fixes.json）のスキップ理由から読み取る。
 *
 * 使い方:
 *   node scripts/check-availability.mjs --from-report   # 除外された商品を自動抽出
 *   node scripts/check-availability.mjs fp-006 tent-011 # ID指定
 *   node scripts/check-availability.mjs --all           # 全商品（245件・5分）
 */
import fs from "node:fs";
import path from "node:path";
import dns from "node:dns";
import { fileURLToPath } from "node:url";
import { loadEnv } from "../src/lib/x-agent-utils.mjs";
import { creatorsApi, credentials, hasCredentials, asinOf } from "../src/lib/amazon-creators-api.mjs";

dns.setDefaultResultOrder("ipv4first");
loadEnv();

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const ROOT = path.join(__dirname, "..");
const PRODUCTS = path.join(ROOT, "data", "products.json");
const RAKUTEN_REPORT = path.join(ROOT, "scratch", "affiliate-link-fixes.json");
const OUT = path.join(ROOT, "scratch", "availability-report.json");

const argv = process.argv.slice(2);
const FROM_REPORT = argv.includes("--from-report");
const ALL = argv.includes("--all");
const idArgs = argv.filter((a) => !a.startsWith("--"));

if (!hasCredentials()) {
  console.error("Creators API認証情報がありません（.env.local を確認）");
  process.exit(1);
}

const products = JSON.parse(fs.readFileSync(PRODUCTS, "utf8"));
const byId = new Map(products.map((p) => [p.id, p]));

// 楽天側の状態を、直近の実行レポートから拾う
const rakutenStatus = new Map();
if (fs.existsSync(RAKUTEN_REPORT)) {
  const r = JSON.parse(fs.readFileSync(RAKUTEN_REPORT, "utf8"));
  for (const s of r.skipped || []) rakutenStatus.set(s.id, s.reason || "");
  for (const f of r.fixes || []) rakutenStatus.set(f.id, "商品ページあり");
}

let targets;
if (idArgs.length > 0) {
  targets = idArgs.map((id) => byId.get(id)).filter(Boolean);
} else if (ALL) {
  targets = products.filter((p) => asinOf(p.amazonUrl));
} else if (FROM_REPORT) {
  // 楽天で「全候補が除外」または「候補0件」だったもの＝買える先が怪しい
  targets = [...rakutenStatus.entries()]
    .filter(([, reason]) => /全候補が除外|候補0件/.test(reason))
    .map(([id]) => byId.get(id))
    .filter(Boolean);
} else {
  console.error("対象を指定してください: --from-report / --all / <商品ID>...");
  process.exit(1);
}

if (targets.length === 0) {
  console.log("対象がありません。先に fix-search-affiliate-links.mjs を実行してください。");
  process.exit(0);
}

console.log(`在庫確認: ${targets.length}件\n`);

const c = credentials();
const results = [];

for (let i = 0; i < targets.length; i += 10) {
  const batch = targets.slice(i, i + 10);
  const withAsin = batch.filter((p) => asinOf(p.amazonUrl));
  const noAsin = batch.filter((p) => !asinOf(p.amazonUrl));

  for (const p of noAsin) {
    results.push({ id: p.id, name: p.name, amazon: "ASIN未設定", rakuten: rakutenStatus.get(p.id) || "-" });
  }

  if (withAsin.length > 0) {
    try {
      const data = await creatorsApi("/catalog/v1/getItems", {
        itemIds: withAsin.map((p) => asinOf(p.amazonUrl)),
        partnerTag: c.partnerTag,
        resources: ["itemInfo.title", "offersV2.listings.price"],
      });
      const items = new Map((data.itemsResult?.items || []).map((it) => [it.asin, it]));
      const errors = new Map((data.errors || []).map((e) => [e.asin || "", e.code]));

      for (const p of withAsin) {
        const asin = asinOf(p.amazonUrl);
        const item = items.get(asin);
        let amazon;
        if (!item) {
          amazon = errors.size ? `ASIN無効(${errors.get(asin) || "不明"})` : "APIに存在しない";
        } else if (!item.offersV2?.listings?.length) {
          amazon = "取扱終了（オファー無し）";
        } else {
          amazon = `販売中 ¥${Math.round(item.offersV2.listings[0].price?.money?.amount ?? 0).toLocaleString()}`;
        }
        results.push({
          id: p.id,
          name: p.name,
          asin,
          amazon,
          amazonTitle: item?.itemInfo?.title?.displayValue || null,
          rakuten: rakutenStatus.get(p.id) || "-",
          productPrice: p.price ?? null,
        });
      }
    } catch (e) {
      console.error(`  バッチ${Math.floor(i / 10) + 1} エラー: ${String(e.message).slice(0, 120)}`);
      for (const p of withAsin) {
        results.push({ id: p.id, name: p.name, amazon: "確認できず", rakuten: rakutenStatus.get(p.id) || "-" });
      }
    }
    if (i + 10 < targets.length) await new Promise((r) => setTimeout(r, 3000));
  }
}

// 両方だめなものを最優先で見せる
const dead = results.filter(
  (r) => !/販売中/.test(r.amazon) && /全候補が除外|候補0件/.test(r.rakuten)
);
const amazonOnly = results.filter((r) => /販売中/.test(r.amazon) && /全候補が除外|候補0件/.test(r.rakuten));

console.log("── 結果 ──\n");
for (const r of results) {
  const mark = /販売中/.test(r.amazon) ? "○" : "✗";
  console.log(`${mark} ${r.name.slice(0, 34)}`);
  console.log(`   Amazon: ${r.amazon}${r.asin ? `  (${r.asin})` : ""}`);
  console.log(`   楽天:   ${r.rakuten}`);
  if (r.amazonTitle && r.productPrice) {
    console.log(`   照合:   ${r.amazonTitle.slice(0, 46)}`);
  }
  console.log();
}

console.log("── まとめ ──");
console.log(`  両方で買えない: ${dead.length}件  ← 記事の見直しが要る`);
console.log(`  Amazonのみ販売: ${amazonOnly.length}件  ← 楽天ボタンを出さない方がよい`);
console.log(`  確認した商品:   ${results.length}件`);

if (dead.length > 0) {
  console.log("\n【両方で買えない商品】");
  for (const r of dead) console.log(`  ${r.id}  ${r.name.slice(0, 40)}`);
}

fs.mkdirSync(path.dirname(OUT), { recursive: true });
fs.writeFileSync(OUT, JSON.stringify({ checkedAt: new Date().toISOString(), results, dead, amazonOnly }, null, 2));
console.log(`\nレポート: ${OUT}`);
