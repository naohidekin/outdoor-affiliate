#!/usr/bin/env node

/**
 * 重複ドラフト記事 + 孤立商品3件を Supabase から直接削除する。
 * (管理画面/ localhost が使えない場合の代替。db:sync はUPSERTのみで削除は伝播しないため専用)
 *
 * 安全設計:
 *  - デフォルトは dry-run（確認表示のみ）。実削除は  --confirm  必須
 *  - 記事は slug と status=draft を検証してから削除（公開版 guide は絶対に消さない）
 *  - 商品は「他の記事(特に公開記事)の product_ids から参照されていない」ことを確認してから削除
 *
 * 使い方:
 *   node scripts/delete-duplicate-power-data.mjs            # dry-run（確認のみ）
 *   node scripts/delete-duplicate-power-data.mjs --confirm  # 実削除
 */

import { createClient } from "@supabase/supabase-js";
import { loadEnv } from "../src/lib/x-agent-utils.mjs";

loadEnv();

const supabaseUrl = process.env.SUPABASE_URL;
const supabaseKey = process.env.SUPABASE_SERVICE_ROLE_KEY;
if (!supabaseUrl || !supabaseKey) {
  console.error("❌ SUPABASE_URL / SUPABASE_SERVICE_ROLE_KEY 未設定。.env.local を確認してください。");
  process.exit(1);
}
const supabase = createClient(supabaseUrl, supabaseKey);
const confirm = process.argv.includes("--confirm");

const TARGET_ARTICLE_SLUG = "portable-power-station-ranking"; // 重複ドラフト（正: portable-power-station-guide は残す）
const TARGET_PRODUCT_IDS = ["power-jackery-1000-new", "power-anker-solix-c1000", "power-ecoflow-river3-plus"];

const log = (...a) => console.log(...a);

async function main() {
  log(`\n=== ${confirm ? "🔴 実削除モード (--confirm)" : "🟡 dry-run モード（確認のみ。実削除は --confirm）"} ===\n`);

  // ── 1. 記事の確認 ──
  const { data: arts, error: aErr } = await supabase
    .from("articles")
    .select("id, slug, title, status")
    .eq("slug", TARGET_ARTICLE_SLUG);
  if (aErr) { console.error("❌ 記事取得エラー:", aErr.message); process.exit(1); }

  let articleToDelete = null;
  if (!arts || arts.length === 0) {
    log(`記事: slug=${TARGET_ARTICLE_SLUG} は見つかりません（既に削除済み？）`);
  } else {
    for (const a of arts) {
      log(`記事候補: id=${a.id} / slug=${a.slug} / status=${a.status} / ${a.title}`);
      if (a.status !== "published") articleToDelete = a;
      else log(`  ⚠️ status=published のため対象外（保護）`);
    }
  }

  // 正版 guide が無事か確認（保険）
  const { data: guide } = await supabase
    .from("articles").select("id, slug, status").eq("slug", "portable-power-station-guide");
  if (guide && guide.length) log(`保護確認: 正版 portable-power-station-guide は存在 (status=${guide[0].status})`);

  // ── 2. 商品の確認（他記事からの参照チェック）──
  log("");
  const { data: prods, error: pErr } = await supabase
    .from("products").select("id, name").in("id", TARGET_PRODUCT_IDS);
  if (pErr) { console.error("❌ 商品取得エラー:", pErr.message); process.exit(1); }
  const existingProductIds = new Set((prods || []).map((p) => p.id));

  // 参照チェック: これらproduct_idを持つ記事を全取得
  const { data: refArts, error: rErr } = await supabase
    .from("articles").select("id, slug, status, product_ids");
  if (rErr) { console.error("❌ 参照チェックのため記事一覧取得エラー:", rErr.message); process.exit(1); }

  const deletableProducts = [];
  for (const pid of TARGET_PRODUCT_IDS) {
    if (!existingProductIds.has(pid)) { log(`商品 ${pid}: 見つかりません（既に削除済み？）`); continue; }
    const refs = (refArts || []).filter(
      (a) => Array.isArray(a.product_ids) && a.product_ids.includes(pid) && a.slug !== TARGET_ARTICLE_SLUG
    );
    if (refs.length) {
      log(`商品 ${pid}: ⚠️ 他記事が参照中のため削除しません → ${refs.map((r) => r.slug + "(" + r.status + ")").join(", ")}`);
    } else {
      deletableProducts.push(pid);
      log(`商品 ${pid}: 削除可（重複ドラフト以外からの参照なし）`);
    }
  }

  // ── 3. 実行 ──
  log("\n--- 削除プラン ---");
  log(`記事: ${articleToDelete ? articleToDelete.id + " (" + articleToDelete.slug + ")" : "なし"}`);
  log(`商品: ${deletableProducts.length ? deletableProducts.join(", ") : "なし"}`);

  if (!confirm) {
    log("\n🟡 dry-run のため実削除しません。問題なければ  --confirm  を付けて再実行してください。");
    return;
  }

  if (articleToDelete) {
    const { error } = await supabase.from("articles").delete().eq("id", articleToDelete.id);
    if (error) console.error(`❌ 記事削除失敗: ${error.message}`);
    else log(`✅ 記事削除: ${articleToDelete.slug} (${articleToDelete.id})`);
  }
  for (const pid of deletableProducts) {
    const { error } = await supabase.from("products").delete().eq("id", pid);
    if (error) console.error(`❌ 商品削除失敗 ${pid}: ${error.message}`);
    else log(`✅ 商品削除: ${pid}`);
  }
  log("\n完了。管理画面/サイトで反映を確認してください（ISRキャッシュは最大1時間）。");
}

main().catch((e) => { console.error(e); process.exit(1); });
