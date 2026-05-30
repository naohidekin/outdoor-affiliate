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
const force = args.includes("--force");

function getHeroType(slug) {
  if (/ranking|budget/.test(slug)) return "tile";
  if (/-vs-|-showdown-|-comparison-|-alternatives/.test(slug)) return "split";
  return "photo";
}

function slugToQuery(slug) {
  const words = slug
    .replace(/-\d{4}(-\d+)?$/, "")
    .replace(/-/g, " ")
    .replace(/\b(ranking|guide|checklist|tips|beginner|review|camp|camping|gear|outdoor)\b/g, "")
    .replace(/\s+/g, " ")
    .trim();
  return `camping outdoor ${words || slug.replace(/-/g, " ")}`;
}

async function fetchUnsplash(query) {
  const url =
    `https://api.unsplash.com/search/photos` +
    `?query=${encodeURIComponent(query)}&orientation=landscape&per_page=1`;
  const resp = await fetch(url, {
    headers: { Authorization: `Client-ID ${ACCESS_KEY}` },
  });
  if (resp.status === 403) throw new Error("Rate limit or invalid key");
  if (!resp.ok) throw new Error(`Unsplash API ${resp.status}`);
  const data = await resp.json();
  return data.results?.[0]?.urls?.regular ?? null;
}

const articles = JSON.parse(readFileSync(join(ROOT, "data/articles.json"), "utf-8"));
let count = 0;

for (const a of articles) {
  if (getHeroType(a.slug) !== "photo") continue;
  if (a.eyecatch && !force) {
    process.stdout.write(`SKIP (already set): ${a.slug}\n`);
    continue;
  }

  const query = slugToQuery(a.slug);
  process.stdout.write(`Fetching: ${a.slug}\n  query: "${query}"\n`);

  try {
    const imageUrl = await fetchUnsplash(query);
    if (imageUrl) {
      process.stdout.write(`  → ${imageUrl.substring(0, 80)}...\n`);
      if (!dryRun) a.eyecatch = imageUrl;
      count++;
    } else {
      process.stdout.write(`  → No results\n`);
    }
    // Unsplash free tier: 50 req/hour → 200ms間隔で安全
    await new Promise((r) => setTimeout(r, 200));
  } catch (e) {
    process.stdout.write(`  ERROR: ${e.message}\n`);
  }
}

if (!dryRun) {
  writeFileSync(join(ROOT, "data/articles.json"), JSON.stringify(articles, null, 2));
  process.stdout.write(`\nDone: ${count}件 eyecatch追加\n`);
} else {
  process.stdout.write(`\nDry run完了: ${count}件 対象\n`);
}
