/**
 * 本番データの読み込み（サーバー専用）
 *
 * 読み込み時に必ず検証を通す。壊れたデータでページを描くくらいなら
 * ビルドを落としたほうがいい。出典の無い互換性情報を英語圏に出すのは、
 * このサイトが避けたい失敗そのもの。
 *
 * data/ 配下のJSONは import ではなく fs で読む。既存のデータ層
 * （src/lib/db.ts）と同じく、ビルド成果物にJSONを抱き込ませないため。
 */

import fs from "node:fs";
import path from "node:path";
import {
  validateDataset,
  type ProductRecord,
  type SourceRecord,
} from "./core";

const DATA_DIR = path.join(process.cwd(), "data", "experiments", "snow-peak-igt");

export type IgtDataset = {
  products: ProductRecord[];
  sources: SourceRecord[];
  /** 全レコードの確認日のうち最も新しいもの。ページに出す */
  lastVerifiedAt: string | null;
};

function readJsonArray(file: string): unknown[] {
  const full = path.join(DATA_DIR, file);
  if (!fs.existsSync(full)) return [];
  const raw = fs.readFileSync(full, "utf8").trim();
  if (raw === "") return [];
  const parsed = JSON.parse(raw);
  if (!Array.isArray(parsed)) {
    throw new Error(`${file} must contain a JSON array`);
  }
  return parsed;
}

let cached: IgtDataset | null = null;

export function loadIgtDataset(): IgtDataset {
  if (cached) return cached;

  const products = readJsonArray("products.json");
  const sources = readJsonArray("sources.json");

  const errors = validateDataset(products, sources);
  if (errors.length > 0) {
    // 何件目が何で落ちたかを全部出す。1件ずつ直させると往復が増える
    throw new Error(
      `Snow Peak IGT dataset is invalid (${errors.length} problem(s)):\n  - ` +
        errors.join("\n  - ")
    );
  }

  const typedProducts = products as ProductRecord[];
  const typedSources = sources as SourceRecord[];

  const dates = [
    ...typedProducts.map((p) => p.lastVerifiedAt),
    ...typedSources.map((s) => s.lastVerifiedAt),
  ].filter((d): d is string => typeof d === "string" && d !== "");

  cached = {
    products: typedProducts,
    sources: typedSources,
    lastVerifiedAt: dates.length > 0 ? dates.sort().at(-1) ?? null : null,
  };
  return cached;
}

/** 出典IDから出典レコードを引く。見つからないものは黙って落とさず null を返す */
export function findSources(
  sourceIds: string[],
  sources: SourceRecord[]
): SourceRecord[] {
  return sourceIds
    .map((id) => sources.find((s) => s.id === id) ?? null)
    .filter((s): s is SourceRecord => s !== null);
}
