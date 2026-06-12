import { readFileSync, writeFileSync } from "fs";
import { join, dirname } from "path";
import { fileURLToPath } from "url";

const __dirname = dirname(fileURLToPath(import.meta.url));
const ROOT = join(__dirname, "..");

// .env.local を読み込む
const envPath = join(ROOT, ".env.local");
const envContent = readFileSync(envPath, "utf-8");
for (const line of envContent.split("\n")) {
  const eq = line.indexOf("=");
  if (eq > 0 && !line.startsWith("#")) {
    const key = line.slice(0, eq).trim();
    const val = line.slice(eq + 1).trim();
    if (!process.env[key]) process.env[key] = val;
  }
}

const ACCESS_KEY = process.env.UNSPLASH_ACCESS_KEY;
if (!ACCESS_KEY) throw new Error("UNSPLASH_ACCESS_KEY が未設定");

const args = process.argv.slice(2);
const dryRun = args.includes("--dry-run");

/**
 * 方針（2026-06-12改修）:
 * 1. クリーンな商品画像（楽天サムネ thumbnail.image.rakuten.co.jp 以外）を
 *    持つ記事は eyecatch を「削除」する。カード・ヒーローとも商品画像が
 *    優先表示され、Unsplash汎用写真より記事内容が伝わるため。
 * 2. クリーンな商品画像が無い記事だけ Unsplash eyecatch を持つ。
 *    その際、サイト全体で写真IDが重複しないよう排他チェックする
 *    （従来は4枚を14記事で使い回し、トップページの「写真かぶり」が発生）。
 * 3. eyecatch を変更した記事は updatedAt を更新する（sync の updatedAt
 *    比較でローカル変更として保持・pushさせるため。これを忘れると反映されない）。
 */

// 楽天マーケット出品者画像（バッジ・加工入り）はカード/ヒーローに不適
function isCleanImage(url) {
  return !!url && !url.includes("thumbnail.image.rakuten.co.jp");
}

// 検索クエリ: 記事テーマに合わせた手動オーバーライド（汎用変換だと
// 同系クエリに収束して似た写真ばかりになるため、テーマ語を明示する）
const QUERY_OVERRIDES = {
  "camp-insect-repellent-guide": "summer forest nature light",
  "oniyamma-shinrinka-review": "dragonfly nature macro",
  "tarp-setup-guide-for-beginners": "tarp shelter campsite",
  "compact-lightweight-chair-ranking": "camping chair lake view",
  "solo-low-chair-ranking": "campfire chair night",
  "gw-camp-checklist-2026": "camping gear packing",
  "tent-vestibule-size-ranking": "tent entrance morning",
  "family-camp-first-time-guide": "family camping kids tent",
  "tent-with-vestibule-ranking": "tent awning campsite",
  "rain-camp-gear-essentials": "rain tent camping",
  "insect-repellent-bracelet-ranking": "kids summer meadow",
};

function slugToQuery(slug) {
  if (QUERY_OVERRIDES[slug]) return QUERY_OVERRIDES[slug];
  const words = slug
    .replace(/-\d{4}(-\d+)?$/, "")
    .replace(/-/g, " ")
    .replace(/\b(ranking|guide|checklist|tips|beginner|review|camp|camping|gear|outdoor)\b/g, "")
    .replace(/\s+/g, " ")
    .trim();
  return `camping outdoor ${words || slug.replace(/-/g, " ")}`;
}

// URLから写真の同一性判定キーを抜く
function photoKey(url) {
  const m = (url || "").match(/photo-([0-9a-f-]+)/i);
  return m ? m[1] : url;
}

async function fetchUnsplashCandidates(query) {
  const url =
    `https://api.unsplash.com/search/photos` +
    `?query=${encodeURIComponent(query)}&orientation=landscape&per_page=10`;
  const resp = await fetch(url, {
    headers: { Authorization: `Client-ID ${ACCESS_KEY}` },
  });
  if (resp.status === 403) throw new Error("Rate limit or invalid key");
  if (!resp.ok) throw new Error(`Unsplash API ${resp.status}`);
  const data = await resp.json();
  return (data.results || []).map((r) => r.urls?.regular).filter(Boolean);
}

const articles = JSON.parse(readFileSync(join(ROOT, "data/articles.json"), "utf-8"));
const products = JSON.parse(readFileSync(join(ROOT, "data/products.json"), "utf-8"));
const productMap = new Map(products.map((p) => [p.id, p]));
const now = new Date().toISOString();

function hasCleanProductImage(article) {
  return (article.productIds || []).some((id) => {
    const p = productMap.get(id);
    return p && isCleanImage(p.imageUrl);
  });
}

let removed = 0;
let assigned = 0;
let kept = 0;

// 使用済み写真キー（重複判定用） key -> 最初に確保した記事のslug
const usedKeys = new Map();

// パス1: 商品画像がある記事は eyecatch 削除
for (const a of articles) {
  if (a.eyecatch && hasCleanProductImage(a)) {
    process.stdout.write(`REMOVE (商品画像あり): ${a.slug}\n`);
    if (!dryRun) {
      delete a.eyecatch;
      a.updatedAt = now;
    }
    removed++;
  }
}

// パス2: 商品画像が無い記事 → ユニークな eyecatch を確保
for (const a of articles) {
  if (hasCleanProductImage(a)) continue;

  // 既存eyecatchがユニークならそのまま確保
  if (a.eyecatch) {
    const key = photoKey(a.eyecatch);
    if (!usedKeys.has(key)) {
      usedKeys.set(key, a.slug);
      kept++;
      process.stdout.write(`KEEP (ユニーク): ${a.slug}\n`);
      continue;
    }
    process.stdout.write(`DUP  (${usedKeys.get(key)} と重複) → 再取得: ${a.slug}\n`);
  }

  const query = slugToQuery(a.slug);
  process.stdout.write(`FETCH: ${a.slug}\n  query: "${query}"\n`);
  try {
    const candidates = await fetchUnsplashCandidates(query);
    const fresh = candidates.find((u) => !usedKeys.has(photoKey(u)));
    if (fresh) {
      usedKeys.set(photoKey(fresh), a.slug);
      process.stdout.write(`  → ${fresh.substring(0, 80)}...\n`);
      if (!dryRun) {
        a.eyecatch = fresh;
        a.updatedAt = now;
      }
      assigned++;
    } else {
      process.stdout.write(`  → ユニークな候補なし（現状維持）\n`);
    }
    // Unsplash free tier: 50 req/hour → 200ms間隔で安全
    await new Promise((r) => setTimeout(r, 200));
  } catch (e) {
    process.stdout.write(`  ERROR: ${e.message}\n`);
  }
}

if (!dryRun) {
  writeFileSync(join(ROOT, "data/articles.json"), JSON.stringify(articles, null, 2) + "\n");
}
process.stdout.write(
  `\n${dryRun ? "[DRY RUN] " : ""}完了: 削除${removed}件 / 新規・差し替え${assigned}件 / 既存維持${kept}件\n`
);
if (!dryRun && (removed || assigned)) {
  process.stdout.write("→ 反映には node scripts/sync-to-supabase.js の実行が必要です\n");
}
