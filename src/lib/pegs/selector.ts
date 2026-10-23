export const PEG_GUIDE_SLUG = "tent-pegs-ground-material-guide";
export const PEG_SELECTOR_MARKER = "<!-- PRODUCT_SELECTOR -->";

export type PegPurchaseLink = {
  url: string;
  destinationUrl: string;
  merchant: string;
  kind: "exact_variant" | "select_at_destination";
  label: string;
  note: string;
  packCount: number;
  manufacturerModel: string;
};

export type PegVariant = {
  id: string;
  name: string;
  series: string;
  sizeLabel: string;
  color: string;
  type: string;
  lengthMm: number | null;
  weightG: number;
  material: string;
  note: string;
  manufacturerUrl: string;
  amazonSearchUrl: string;
  purchaseLinks: PegPurchaseLink[];
};

export const PEG_FILTER_FIELDS = ["sizeLabel", "color", "type"] as const;
export type PegFilterField = (typeof PEG_FILTER_FIELDS)[number];
export type PegFilters = Record<PegFilterField, string>;

export function splitPegGuide(content: string): [string, string] {
  const parts = content.split(PEG_SELECTOR_MARKER);
  if (parts.length !== 2) throw new Error("Peg guide requires exactly one selector marker");
  return [parts[0], parts[1]];
}

export function filterPegVariants(variants: readonly PegVariant[], filters: PegFilters): PegVariant[] {
  return variants.filter((variant) => PEG_FILTER_FIELDS.every((field) => !filters[field] || filters[field] === variant[field]));
}

export function pegFilterOptions(variants: readonly PegVariant[], field: PegFilterField): string[] {
  return [...new Set(variants.map((variant) => variant[field]))].sort((a, b) => a.localeCompare(b, "ja", { numeric: true }));
}

function object(value: unknown): Record<string, unknown> {
  if (!value || typeof value !== "object" || Array.isArray(value)) throw new Error("Invalid peg record");
  return value as Record<string, unknown>;
}
function text(value: unknown): string {
  if (typeof value !== "string" || !value.trim() || value.length > 1200) throw new Error("Invalid peg text");
  return value;
}
function https(value: unknown): URL {
  const raw = text(value);
  if (/[\s\\]/.test(raw)) throw new Error("Invalid URL");
  const url = new URL(raw);
  if (url.protocol !== "https:" || url.username || url.password || url.port || url.hash) throw new Error("Invalid HTTPS URL");
  return url;
}
function positive(value: unknown): number {
  if (typeof value !== "number" || !Number.isFinite(value) || value <= 0) throw new Error("Invalid peg measurement");
  return value;
}
function purchase(value: unknown): PegPurchaseLink {
  const row = object(value), link = https(row.url), destination = https(row.destinationUrl);
  if (destination.hostname !== "item.rakuten.co.jp" || !/^\/[^/]+\/[^/]+\/$/.test(destination.pathname) || destination.search
    || link.hostname !== "hb.afl.rakuten.co.jp" || link.pathname !== "/ichiba/18eb3228.621d8df3.18eb3229.ec5f8d49/"
    || link.searchParams.get("pc") !== destination.href || link.searchParams.get("link_type") !== "text"
    || [...link.searchParams.keys()].sort().join(",") !== "link_type,pc") throw new Error("Invalid peg purchase destination");
  if (row.kind !== "exact_variant" && row.kind !== "select_at_destination") throw new Error("Invalid purchase kind");
  const packCount = positive(row.packCount);
  if (!Number.isSafeInteger(packCount)) throw new Error("Invalid pack count");
  return { url: text(row.url), destinationUrl: text(row.destinationUrl), merchant: text(row.merchant),
    kind: row.kind, label: text(row.label), note: text(row.note), packCount, manufacturerModel: text(row.manufacturerModel) };
}

/** Whitelist public fields; private source records and image URLs never enter client props. */
export function publicPegVariants(raw: unknown): PegVariant[] {
  if (!Array.isArray(raw) || !raw.length) throw new Error("Expected peg variants");
  const ids = new Set<string>();
  return raw.map((value) => {
    const row = object(value), id = text(row.id);
    if (!/^[a-z0-9-]+$/.test(id) || ids.has(id)) throw new Error("Duplicate or invalid peg ID");
    ids.add(id);
    const manufacturer = https(row.manufacturerUrl), amazon = https(row.amazonSearchUrl);
    if (!["ec.snowpeak.co.jp", "www.muranokajiya.jp", "cascadedesigns.com"].includes(manufacturer.hostname)) throw new Error("Invalid manufacturer URL");
    if (amazon.hostname !== "www.amazon.co.jp" || amazon.pathname !== "/s" || !amazon.searchParams.get("k")?.trim()
      || amazon.searchParams.get("tag") !== "camp78-22"
      || [...amazon.searchParams.keys()].sort().join(",") !== "k,tag") throw new Error("Invalid Amazon search URL");
    if (!Array.isArray(row.purchaseLinks)) throw new Error("Expected purchase links");
    return { id, name: text(row.name), series: text(row.series), sizeLabel: text(row.sizeLabel),
      color: text(row.color), type: text(row.type), lengthMm: row.lengthMm === null ? null : positive(row.lengthMm),
      weightG: positive(row.weightG), material: text(row.material), note: row.note === "" ? "" : text(row.note),
      manufacturerUrl: text(row.manufacturerUrl), amazonSearchUrl: text(row.amazonSearchUrl),
      purchaseLinks: row.purchaseLinks.map(purchase) };
  });
}
