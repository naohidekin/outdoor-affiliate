#!/usr/bin/env node
/**
 * scripts/insert-article-images.mjs
 *
 * Unsplash API を使って全記事に雰囲気画像を挿入する
 *
 * 使い方:
 *   node scripts/insert-article-images.mjs --dry-run       # プレビューのみ
 *   node scripts/insert-article-images.mjs --slug=xxx      # 特定記事のみ
 *   node scripts/insert-article-images.mjs                 # 全記事（published のみ）
 *   node scripts/insert-article-images.mjs --all           # draft 含む全記事
 */

import { createClient } from "@supabase/supabase-js";
import fs from "fs";
import path from "path";
import { fileURLToPath } from "url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const ENV_PATH = path.join(__dirname, "../.env.local");

// 環境変数を手動ロード
for (const line of fs.readFileSync(ENV_PATH, "utf-8").split("\n")) {
  const m = line.match(/^([A-Z_]+)=(.+)$/);
  if (m) process.env[m[1]] = m[2].trim();
}

const UNSPLASH_KEY = process.env.UNSPLASH_ACCESS_KEY;
const SUPABASE_URL = process.env.SUPABASE_URL || process.env.NEXT_PUBLIC_SUPABASE_URL;
const SUPABASE_KEY = process.env.SUPABASE_SERVICE_ROLE_KEY;

if (!UNSPLASH_KEY) throw new Error("UNSPLASH_ACCESS_KEY が未設定です");
const sb = createClient(SUPABASE_URL, SUPABASE_KEY);

const args = process.argv.slice(2);
const DRY_RUN = args.includes("--dry-run");
const SLUG_ARG = args.find(a => a.startsWith("--slug="))?.split("=")[1];
const ALL = args.includes("--all");

// === カテゴリ別 Unsplash 検索クエリ ===
const CATEGORY_QUERIES = {
  tent:           ["family camping tent forest", "camping tent setup outdoor", "tent camping night stars"],
  "sleeping-bag": ["sleeping bag camping outdoor", "camping morning sunrise warm", "winter camping cozy"],
  burner:         ["camping stove cooking fire", "outdoor cooking camp kitchen", "camp stove boiling water"],
  backpack:       ["hiking backpack trail mountain", "trekking outdoor adventure forest", "hiker mountain path"],
  tarp:           ["tarp shelter camping rain forest", "hammock camping woods", "outdoor shelter trees"],
  lantern:        ["camping lantern night glow", "camping light evening outdoor", "lantern campsite warm"],
  firepit:        ["campfire fire pit night outdoor", "bonfire camping evening", "campfire cooking flames"],
  chair:          ["camping chair sunset outdoor", "relax camp chair nature", "outdoor chair riverside"],
  table:          ["camping table outdoor meal", "camp kitchen table setup", "outdoor dining nature picnic"],
  cooler:         ["camping cooler ice cold drinks", "camp food prep outdoor", "picnic cooler nature"],
  wear:           ["outdoor hiking clothing adventure", "camping fashion trail", "trekking gear apparel"],
  shoes:          ["hiking boots trail muddy", "trekking shoes mountain path", "outdoor footwear forest"],
  general:        ["camping outdoor nature adventure", "campsite forest morning", "outdoor gear camp"],
};

// === Unsplash 画像プール取得 ===
const imagePool = {}; // category -> [{ url, alt, credit }]

async function fetchPool(category) {
  if (imagePool[category]) return;
  const queries = CATEGORY_QUERIES[category] || CATEGORY_QUERIES.general;
  const pool = [];
  for (const q of queries) {
    try {
      const res = await fetch(
        `https://api.unsplash.com/search/photos?query=${encodeURIComponent(q)}&per_page=10&orientation=landscape`,
        { headers: { Authorization: `Client-ID ${UNSPLASH_KEY}` } }
      );
      const data = await res.json();
      if (data.results) {
        for (const photo of data.results) {
          pool.push({
            url: photo.urls.regular + "&w=1200&q=80",
            alt: photo.alt_description || q,
            credit: `${photo.user.name}`,
            creditUrl: `${photo.user.links.html}?utm_source=camp_gear_lab&utm_medium=referral`,
          });
        }
      }
      // レート制限対策: 0.5秒待機
      await new Promise(r => setTimeout(r, 500));
    } catch (e) {
      console.warn(`  Unsplash 取得失敗 (${q}):`, e.message);
    }
  }
  imagePool[category] = pool;
  console.log(`  [pool] ${category}: ${pool.length} 枚取得`);
}

let poolUsageCount = {}; // category -> index（使用済みインデックス）

function pickImage(category) {
  const pool = imagePool[category] || imagePool.general || [];
  if (!pool.length) return null;
  const idx = poolUsageCount[category] || 0;
  poolUsageCount[category] = (idx + 1) % pool.length;
  return pool[idx];
}

function buildImageMarkdown(photo, size = "full") {
  if (!photo) return "";
  const widthClass = size === "full" ? "" : "";
  return [
    ``,
    `![${photo.alt}](${photo.url})`,
    `*Photo by [${photo.credit}](${photo.creditUrl}) on [Unsplash](https://unsplash.com/?utm_source=camp_gear_lab&utm_medium=referral)*`,
    ``,
  ].join("\n");
}

// === 画像挿入ロジック ===
function insertImages(content, categorySlug) {
  if (!content) return content;

  // 既に画像があればスキップ
  if (/!\[.*?\]\(https?:\/\/images\.unsplash\.com/.test(content)) {
    return null; // null = skip (既挿入)
  }

  const lines = content.split("\n");
  const result = [];
  let h2Count = 0;
  let insertedCount = 0;
  let introInserted = false;
  let prevLineWasSeparator = false;

  for (let i = 0; i < lines.length; i++) {
    const line = lines[i];
    const isH2 = /^## /.test(line);
    const isSeparator = line.trim() === "---";
    const isComponent = /^\{\{(comparison|ranking):/.test(line);

    // イントロ後（最初の --- の直前）に1枚目を挿入
    if (!introInserted && isSeparator && h2Count === 0) {
      const photo = pickImage(categorySlug);
      if (photo) {
        result.push(buildImageMarkdown(photo));
        insertedCount++;
      }
      introInserted = true;
    }

    // H2 カウント
    if (isH2) {
      h2Count++;

      // comparison / ranking の直前は画像を入れない
      const nextNonEmpty = lines.slice(i + 1).find(l => l.trim() !== "");
      const nextIsComponent = nextNonEmpty && /^\{\{(comparison|ranking):/.test(nextNonEmpty);

      // 2番目のH2の後（おすすめランキングや詳細レビューの手前ではない）に挿入
      if (h2Count === 2 && !nextIsComponent && insertedCount < 2) {
        result.push(line);
        const photo = pickImage(categorySlug);
        if (photo) {
          result.push(buildImageMarkdown(photo));
          insertedCount++;
        }
        continue;
      }

      // 最後から2番目のH2（まとめの直前）に挿入
      const remainingH2s = lines.slice(i + 1).filter(l => /^## /.test(l)).length;
      if (remainingH2s === 0 && insertedCount < 3) {
        result.push(line);
        const photo = pickImage(categorySlug);
        if (photo) {
          result.push(buildImageMarkdown(photo));
          insertedCount++;
        }
        continue;
      }
    }

    result.push(line);
    prevLineWasSeparator = isSeparator;
  }

  return result.join("\n");
}

// === カテゴリスラッグ取得 ===
async function getCategorySlug(categoryId) {
  const { data } = await sb.from("categories").select("slug").eq("id", categoryId).single();
  return data?.slug || "general";
}

// === メイン ===
async function main() {
  console.log(`\n=== insert-article-images ${DRY_RUN ? "[DRY RUN]" : ""} ===\n`);

  // 記事取得
  let query = sb.from("articles").select("id,slug,title,content,categoryId:category_id");
  if (SLUG_ARG) {
    query = query.eq("slug", SLUG_ARG);
  } else if (!ALL) {
    query = query.eq("status", "published");
  }
  const { data: articles, error } = await query;
  if (error) throw error;

  console.log(`対象記事: ${articles.length} 件\n`);

  // カテゴリプール事前取得
  const categoryIds = [...new Set(articles.map(a => a.categoryId))];
  console.log("Unsplash 画像プール取得中...");
  for (const catId of categoryIds) {
    const slug = await getCategorySlug(catId);
    await fetchPool(slug);
  }
  console.log();

  let updated = 0, skipped = 0, failed = 0;

  for (const article of articles) {
    const catSlug = await getCategorySlug(article.categoryId);
    const newContent = insertImages(article.content, catSlug);

    if (newContent === null) {
      console.log(`  SKIP [既挿入] ${article.slug}`);
      skipped++;
      continue;
    }
    if (newContent === article.content) {
      console.log(`  SKIP [変更なし] ${article.slug}`);
      skipped++;
      continue;
    }

    // 挿入された画像数をカウント
    const imgCount = (newContent.match(/images\.unsplash\.com/g) || []).length;
    console.log(`  UPDATE [+${imgCount}枚] ${article.slug} — ${article.title.slice(0, 40)}`);

    if (!DRY_RUN) {
      const { error: upErr } = await sb
        .from("articles")
        .update({ content: newContent, updated_at: new Date().toISOString() })
        .eq("id", article.id);
      if (upErr) {
        console.error(`    エラー: ${upErr.message}`);
        failed++;
      } else {
        updated++;
      }
    } else {
      // dry-run: 差分プレビュー
      const sample = newContent.split("\n").filter(l => l.includes("unsplash.com")).slice(0, 2);
      sample.forEach(l => console.log(`    → ${l.slice(0, 80)}...`));
      updated++;
    }

    // レート制限対策
    await new Promise(r => setTimeout(r, 200));
  }

  console.log(`\n完了: 更新 ${updated} / スキップ ${skipped} / エラー ${failed}`);
  if (DRY_RUN) console.log("（--dry-run のため実際の更新は行っていません）");
}

main().catch(e => { console.error(e); process.exit(1); });
