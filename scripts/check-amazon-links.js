#!/usr/bin/env node

/**
 * Amazonリンク切れ自動チェック
 * products.jsonのamazonUrlを全件チェックし、無効なリンクを検出
 *
 * 2026-08-10 改修: HTMLスクレイピングから Creators API の getItems へ移行した。
 * 7/30 は ok=313 / errors=0 だったのが、8/9 の定期実行では
 * **350件すべてが "fetch failed"（ok=0）** になっていた。Amazon側が
 * 接続レベルで弾いていると見られる。しかも全件が errors に落ちるため
 * broken は常に0件になり、後段の link-fix は何もすることが無くなり、
 * 管理画面は「リンク切れはありません🎉」と表示し続けていた。
 * 監視が沈黙して壊れている状態で、これが一番たちが悪い。
 *
 * getItems なら在庫・取扱終了を公式に判定できる。判定規則は
 * check-availability.mjs / link-fix.mjs と揃える:
 *   itemsResult に居てオファーあり  → 正常
 *   itemsResult に居るがオファー無し → 取扱終了（＝クリックされても1円にならない）
 *   errors で ItemNotAccessible 等  → ASIN消滅
 * 認証情報が無い環境では従来のHTTPチェックに落ちる。
 *
 * 使い方:
 *   node scripts/check-amazon-links.js
 *   node scripts/check-amazon-links.js --http   (強制的に旧HTTPチェック)
 */

import fs from "fs";
import path from "path";
import dns from "node:dns";
import { fileURLToPath } from "url";
import {
  creatorsApi,
  credentials,
  hasCredentials,
  asinOf,
} from "../src/lib/amazon-creators-api.mjs";

dns.setDefaultResultOrder("ipv4first");

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const DATA_DIR = path.join(__dirname, "..", "data");

// .env.local を手動読み込み
const envPath = path.join(__dirname, "..", ".env.local");
if (fs.existsSync(envPath)) {
  const envContent = fs.readFileSync(envPath, "utf-8");
  for (const line of envContent.split("\n")) {
    const match = line.match(/^([^#=]+)=(.*)$/);
    if (match && !process.env[match[1].trim()]) {
      process.env[match[1].trim()] = match[2].trim();
    }
  }
}

const FORCE_HTTP = process.argv.includes("--http");
const CONCURRENCY = 5;
const REQUEST_DELAY = 1000; // 1秒間隔（Amazon制限回避）

async function checkUrl(url) {
  try {
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), 15000);

    const res = await fetch(url, {
      method: "GET",
      signal: controller.signal,
      redirect: "follow",
      headers: {
        "User-Agent":
          "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        Accept: "text/html,application/xhtml+xml",
        "Accept-Language": "ja,en;q=0.9",
      },
    });

    clearTimeout(timeout);

    const text = await res.text();

    // Amazonの「ページが見つかりません」チェック
    const isNotFound =
      res.status === 404 ||
      text.includes("ページが見つかりません") ||
      text.includes("currently unavailable") ||
      text.includes("Page Not Found");

    // 「犬」ページ（Amazon 404相当）チェック
    const isDogPage =
      text.includes("SORRY") && text.includes("www.amazon.co.jp");

    return {
      status: res.status,
      ok: res.ok && !isNotFound && !isDogPage,
      redirected: res.redirected,
      finalUrl: res.url,
      notFound: isNotFound || isDogPage,
    };
  } catch (err) {
    return {
      status: 0,
      ok: false,
      error: err.message,
      notFound: false,
    };
  }
}

function sleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

const GETITEMS_BATCH = 10; // getItems の1回あたり上限
const GETITEMS_DELAY = 3000;

/**
 * Creators API で在庫を確定判定する。
 * 返り値は旧HTTPチェックと同じ {ok, broken, errors} の3分類。
 */
async function checkViaCreatorsApi(withUrl) {
  const ok = [];
  const broken = [];
  const errors = [];
  const partnerTag = credentials().partnerTag;

  // 検索URLはASINが無いので getItems にかけられない。
  // ページ自体は開けるので broken には入れない（link-fix に隔離させない）
  const targets = [];
  for (const p of withUrl) {
    if (asinOf(p.amazonUrl)) targets.push(p);
    else {
      errors.push({ product: p, result: { error: "検索URL（ASIN未確定）" } });
      process.stdout.write(`  ⚠️ ${p.id} ${p.name.slice(0, 25)} → 検索URL\n`);
    }
  }

  /** オファーの有無と価格の有無は別物。価格が取れなくても出品があれば買える */
  const hasOffer = (item) => (item.offersV2?.listings || []).length > 0;

  const classify = (p, item, errCode) => {
    if (!item) {
      broken.push({ product: p, result: { notFound: true, error: `ASIN無効(${errCode || "不明"})` } });
      process.stdout.write(`  🚨 ${p.id} ${p.name.slice(0, 25)} → ASIN無効\n`);
    } else if (!hasOffer(item)) {
      broken.push({ product: p, result: { notFound: true, error: "取扱終了（オファー無し）" } });
      process.stdout.write(`  🚨 ${p.id} ${p.name.slice(0, 25)} → 取扱終了\n`);
    } else {
      ok.push(p);
      process.stdout.write(`  ✅ ${p.id} ${p.name.slice(0, 25)}\n`);
    }
  };

  for (let i = 0; i < targets.length; i += GETITEMS_BATCH) {
    const batch = targets.slice(i, i + GETITEMS_BATCH);
    const payload = {
      partnerTag,
      resources: ["itemInfo.title", "offersV2.listings.price"],
    };
    try {
      const data = await creatorsApi("/catalog/v1/getItems", {
        ...payload,
        itemIds: batch.map((p) => asinOf(p.amazonUrl)),
      });
      const items = new Map((data.itemsResult?.items || []).map((it) => [it.asin, it]));
      const errMap = new Map((data.errors || []).map((e) => [e.asin || "", e.code]));
      for (const p of batch) {
        const asin = asinOf(p.amazonUrl);
        classify(p, items.get(asin), errMap.get(asin));
      }
    } catch (e) {
      // バッチ単位で落ちると無関係な9件まで巻き添えになるので個別に再試行する
      process.stdout.write(
        `  … バッチ${Math.floor(i / GETITEMS_BATCH) + 1} 失敗（個別に再試行）\n`
      );
      for (const p of batch) {
        await sleep(1200);
        try {
          const d = await creatorsApi("/catalog/v1/getItems", {
            ...payload,
            itemIds: [asinOf(p.amazonUrl)],
          });
          classify(p, (d.itemsResult?.items || [])[0], (d.errors || [])[0]?.code);
        } catch (e2) {
          errors.push({ product: p, result: { error: String(e2.message).slice(0, 60) } });
          process.stdout.write(`  ⚠️ ${p.id} ${p.name.slice(0, 25)} → 確認できず\n`);
        }
      }
    }
    if (i + GETITEMS_BATCH < targets.length) await sleep(GETITEMS_DELAY);
  }

  return { ok, broken, errors };
}

/** 旧方式。認証情報が無い環境向けのフォールバック */
async function checkViaHttp(withUrl) {
  const ok = [];
  const broken = [];
  const errors = [];

  for (let i = 0; i < withUrl.length; i += CONCURRENCY) {
    const batch = withUrl.slice(i, i + CONCURRENCY);
    const results = await Promise.all(
      batch.map(async (product) => ({ product, result: await checkUrl(product.amazonUrl) }))
    );

    for (const { product, result } of results) {
      if (result.ok) {
        ok.push(product);
        process.stdout.write(`  ✅ ${product.id} ${product.name.slice(0, 25)}\n`);
      } else if (result.notFound) {
        broken.push({ product, result });
        process.stdout.write(`  🚨 ${product.id} ${product.name.slice(0, 25)} → 404/不存在\n`);
      } else {
        errors.push({ product, result });
        process.stdout.write(
          `  ⚠️ ${product.id} ${product.name.slice(0, 25)} → ${(result.error || `HTTP ${result.status}`).slice(0, 40)}\n`
        );
      }
    }

    if (i + CONCURRENCY < withUrl.length) await sleep(REQUEST_DELAY);
  }

  return { ok, broken, errors };
}

async function main() {
  const products = JSON.parse(
    fs.readFileSync(path.join(DATA_DIR, "products.json"), "utf-8")
  );

  // Amazonに存在しない商品（ふるさと納税の利用券・楽天専売のOEM品など）は
  // 「URL未設定」に並べても直しようがないので、理由つきで別枠にする
  let excluded = new Map();
  try {
    const f = JSON.parse(
      fs.readFileSync(path.join(DATA_DIR, "amazon-match-exclusions.json"), "utf-8")
    );
    for (const e of f.exclusions || []) excluded.set(e.id, e.reason);
  } catch {
    /* 無ければ除外なしで動く */
  }

  const withUrl = products.filter((p) => p.amazonUrl);
  const withoutUrl = products.filter((p) => !p.amazonUrl && !excluded.has(p.id));
  const notOnAmazon = products.filter((p) => !p.amazonUrl && excluded.has(p.id));

  console.log(`\n📦 商品数: ${products.length}`);
  console.log(`🔗 Amazon URL あり: ${withUrl.length}`);
  console.log(`❌ Amazon URL なし: ${withoutUrl.length}`);

  if (notOnAmazon.length > 0) {
    console.log(`\n--- Amazonに存在しない商品（対象外・${notOnAmazon.length}件） ---`);
    notOnAmazon.forEach((p) => console.log(`  ${p.id}: ${p.name} … ${excluded.get(p.id)}`));
  }

  if (withoutUrl.length > 0) {
    console.log("\n--- URL未設定の商品 ---");
    withoutUrl.forEach((p) => console.log(`  ${p.id}: ${p.name}`));
  }

  const useApi = !FORCE_HTTP && hasCredentials();
  console.log(
    `\n🔍 リンクチェック開始（${withUrl.length}件・${useApi ? "Creators API" : "HTTP"}）...\n`
  );
  if (!useApi && !FORCE_HTTP) {
    console.log(
      "  ⚠️ Creators API認証情報が無いためHTTPで確認します。" +
        "Amazonに弾かれて全件エラーになることがあります\n"
    );
  }

  const { ok, broken, errors } = useApi
    ? await checkViaCreatorsApi(withUrl)
    : await checkViaHttp(withUrl);

  // 監視が沈黙して壊れるのを防ぐ。8/9はこれが無くて全滅に気づけなかった
  if (withUrl.length > 0 && ok.length === 0) {
    console.log(
      "\n🛑 正常判定が1件もありません。チェック自体が壊れている可能性が高いです" +
        `（確認 ${withUrl.length}件 / エラー ${errors.length}件）`
    );
  }

  // レポート
  console.log("\n========== レポート ==========");
  console.log(`✅ 正常: ${ok.length}件`);
  console.log(`🚨 リンク切れ: ${broken.length}件`);
  console.log(`⚠️ エラー: ${errors.length}件`);

  if (broken.length > 0) {
    console.log("\n--- リンク切れ商品 ---");
    broken.forEach(({ product }) => {
      console.log(`  ${product.id}: ${product.name}`);
      console.log(`    URL: ${product.amazonUrl}`);
    });
  }

  if (errors.length > 0) {
    console.log("\n--- エラー商品 ---");
    errors.forEach(({ product, result }) => {
      console.log(`  ${product.id}: ${product.name}`);
      console.log(
        `    URL: ${product.amazonUrl}`
      );
      console.log(
        `    理由: ${result.error || `HTTP ${result.status}`}`
      );
    });
  }

  // ─── YouTube埋め込みの死活チェック ───
  // 記事内の {{youtube:ID}} をoEmbedで確認する（404/401=削除・非公開）。
  // 他人の動画は消えることがあるため、週次でここに載せて放置事故を防ぐ。
  const articles = JSON.parse(
    fs.readFileSync(path.join(DATA_DIR, "articles.json"), "utf-8")
  );
  const ytRefs = [];
  for (const a of articles) {
    if (a.status !== "published") continue;
    for (const m of (a.content || "").matchAll(
      /\{\{youtube:([A-Za-z0-9_-]{6,20})(?:\|[^}]*)?\}\}/g
    )) {
      ytRefs.push({ slug: a.slug, videoId: m[1] });
    }
  }
  const deadVideos = [];
  if (ytRefs.length > 0) {
    console.log(`\n🎬 YouTube埋め込みチェック（${ytRefs.length}件）...`);
    for (const ref of ytRefs) {
      try {
        const res = await fetch(
          `https://www.youtube.com/oembed?url=https%3A%2F%2Fwww.youtube.com%2Fwatch%3Fv%3D${ref.videoId}&format=json`
        );
        if (res.status === 404 || res.status === 401 || res.status === 403) {
          deadVideos.push(ref);
          console.log(`  🚨 消滅/非公開: ${ref.videoId}（記事: ${ref.slug}）`);
        }
      } catch {
        // ネットワークエラーは判定不能（安全側: 報告しない）
      }
      await sleep(500);
    }
    if (deadVideos.length === 0) console.log("  ✅ 全動画が視聴可能");
  }

  // 結果をJSONファイルに保存（他スクリプトから参照用）
  const report = {
    deadVideos,
    checkedAt: new Date().toISOString(),
    total: products.length,
    checked: withUrl.length,
    ok: ok.length,
    broken: broken.map(({ product }) => ({
      id: product.id,
      name: product.name,
      url: product.amazonUrl,
    })),
    errors: errors.map(({ product, result }) => ({
      id: product.id,
      name: product.name,
      url: product.amazonUrl,
      reason: result.error || `HTTP ${result.status}`,
    })),
    noUrl: withoutUrl.map((p) => ({ id: p.id, name: p.name })),
  };

  fs.writeFileSync(
    path.join(DATA_DIR, "link-check-report.json"),
    JSON.stringify(report, null, 2),
    "utf-8"
  );
  console.log("\n📄 レポート保存: data/link-check-report.json");
}

main().catch((err) => {
  console.error("エラー:", err.message);
  process.exit(1);
});
