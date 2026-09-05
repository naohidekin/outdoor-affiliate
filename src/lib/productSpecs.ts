import type { Product } from "./types.ts";

const LABELS: Record<string, string> = {
  weight: "重量", capacity: "容量", size: "サイズ", dimensions: "サイズ",
  material: "素材", opening: "口径", runtime: "連続使用時間",
  brightness: "明るさ", waterproof: "防水性能", power: "電源",
};
const PRIORITY: Record<string, string[]> = {
  tent: ["定員", "重量", "サイズ", "収納サイズ", "耐水圧"],
  cooler: ["容量", "重量", "サイズ", "保冷力", "電源"],
  "sleeping-bag": ["快適温度", "対応温度", "重量", "収納サイズ", "素材"],
  light: ["明るさ", "連続点灯時間", "電源", "防水性能", "重量"],
  fan: ["電源", "連続使用時間", "重量", "サイズ"],
  "insect-repellent": ["有効成分", "対象害虫", "対象年齢", "種別"],
};

/** Skip empty values and translate known API labels without inventing specifications. */
export function getProductSpecs(product: Pick<Product, "categoryId" | "specs">, limit = Infinity): [string, string][] {
  const values = new Map<string, string>();
  // Prefer an explicit Japanese field when both an API alias and Japanese field exist.
  const entries = Object.entries(product.specs ?? {}).sort(([a], [b]) => Number(Boolean(LABELS[a])) - Number(Boolean(LABELS[b])));
  for (const [rawKey, rawValue] of entries) {
    const key = LABELS[rawKey.trim()] ?? rawKey.trim();
    const value = String(rawValue ?? "").trim();
    if (!key || !value || /^(?:[-—–]+|null|undefined|n\/?a)$/i.test(value)) continue;
    if (/^[a-z_\s]+$/i.test(key) && !LABELS[rawKey.trim()]) continue;
    if (!values.has(key)) values.set(key, value);
  }
  const priority = PRIORITY[product.categoryId] ?? ["重量", "サイズ", "素材", "容量"];
  const score = (key: string) => priority.includes(key) ? priority.indexOf(key) : priority.length;
  return [...values].sort(([a], [b]) => score(a) - score(b)).slice(0, limit);
}
