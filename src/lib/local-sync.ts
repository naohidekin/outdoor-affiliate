import fs from "fs";
import path from "path";
import { getArticles, getCategories, getProducts } from "./db";
import { isSupabaseConfigured } from "./supabase";

const DATA_DIR = path.join(process.cwd(), "data");

function isWritableLocalFs(): boolean {
  // Vercel/Lambda 環境では process.cwd() の data/ は読み取り専用
  // 開発環境のみ書き戻す
  if (process.env.VERCEL || process.env.AWS_LAMBDA_FUNCTION_NAME) return false;
  try {
    fs.accessSync(DATA_DIR, fs.constants.W_OK);
    return true;
  } catch {
    return false;
  }
}

function writeJsonAtomic(filename: string, data: unknown): void {
  const filepath = path.join(DATA_DIR, filename);
  const tmppath = `${filepath}.tmp`;
  fs.writeFileSync(tmppath, JSON.stringify(data, null, 2));
  fs.renameSync(tmppath, filepath);
}

/**
 * Supabase の最新状態をローカルJSONに書き戻す
 *
 * 用途:
 *   - 管理画面で公開した直後に呼び、ローカルJSONをSupabaseと一致させる
 *   - これにより次回 `sync-to-supabase.js` がステイルなローカル値で
 *     Supabase上の更新を上書きするバグを予防する
 *
 * 失敗時:
 *   - Vercel等の読み取り専用FSでは静かに何もしない
 *   - Supabase未設定時も静かに何もしない
 */
export async function pullFromSupabase(): Promise<{
  ok: boolean;
  reason?: string;
  counts?: { articles: number; products: number; categories: number };
}> {
  if (!isSupabaseConfigured()) {
    return { ok: false, reason: "supabase-not-configured" };
  }
  if (!isWritableLocalFs()) {
    return { ok: false, reason: "fs-not-writable" };
  }

  try {
    const [articles, products, categories] = await Promise.all([
      getArticles(),
      getProducts(),
      getCategories(),
    ]);

    writeJsonAtomic("articles.json", articles);
    writeJsonAtomic("products.json", products);
    writeJsonAtomic("categories.json", categories);

    console.log(
      `[local-sync] ✅ pulled ${articles.length} articles / ${products.length} products / ${categories.length} categories`
    );

    return {
      ok: true,
      counts: {
        articles: articles.length,
        products: products.length,
        categories: categories.length,
      },
    };
  } catch (err) {
    const msg = err instanceof Error ? err.message : String(err);
    console.error(`[local-sync] ❌ ${msg}`);
    return { ok: false, reason: msg };
  }
}
