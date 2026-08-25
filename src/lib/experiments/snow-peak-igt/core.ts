/**
 * Snow Peak IGT 需要検証MVP — 中核ロジック（型・正規化・検索・判定文言・検証）
 *
 * このファイルは**他の .ts をランタイムimportしない**。
 * テストを新規依存なしで回すため（`node --test` の型ストリップ実行では
 * 拡張子省略のimportが解決できない）。分割したい誘惑はあるが、
 * 分割した瞬間にテストが動かなくなる。
 *
 * 方針上いちばん大事なのは「分からないことを分かったように書かない」こと。
 * 欠損は空文字や0ではなく Unknown / Insufficient evidence として扱う。
 */

// ─── 型 ───────────────────────────────────────────────

export type ProductStatus = "current" | "discontinued" | "unknown";
export type CompatibilityStatus = "confirmed" | "not_confirmed" | "unknown";
export type Market = "us" | "jp" | "other";

export type CompatibilityRecord = {
  targetId: string;
  status: CompatibilityStatus;
  sourceIds: string[];
  notes?: string;
};

export type PurchaseOption = {
  market: Market;
  merchant: string;
  url: string;
  affiliate: boolean;
};

export type ProductRecord = {
  id: string;
  productName: string;
  aliases: string[];
  japaneseModelNumber: string | null;
  usModelNumber: string | null;
  status: ProductStatus;
  confirmedSuccessorId: string | null;
  compatibility: CompatibilityRecord[];
  sourceIds: string[];
  lastVerifiedAt: string;
  purchaseOptions: PurchaseOption[];
};

export type SourceType =
  | "official_product_page"
  | "official_manual"
  | "official_archive"
  | "official_support";

export type SourceRecord = {
  id: string;
  publisher: string;
  title: string;
  url: string;
  sourceType: SourceType;
  lastVerifiedAt: string;
};

// ─── 表示文言 ─────────────────────────────────────────

/**
 * 判定に使ってよい表現はこの4つだけ。
 * 「Probably compatible」「Should fit」「Guaranteed compatible」のような
 * 推測・保証は、根拠が無いのに読者へ責任を負わせるので使わない。
 */
export const EVIDENCE_STATEMENTS = {
  confirmed: "Confirmed by official documentation",
  currentEquivalent: "Current equivalent identified",
  discontinuedNoSuccessor: "Discontinued — no confirmed successor",
  insufficient: "Insufficient evidence",
} as const;

export type EvidenceStatement =
  (typeof EVIDENCE_STATEMENTS)[keyof typeof EVIDENCE_STATEMENTS];

/** 値が無いときの表示。空欄や 0 で誤魔化さない */
export const UNKNOWN_LABEL = "Unknown";

/**
 * 出してはいけない表現。テストでソースを走査して弾く。
 * 「たぶん合う」を一度でも書くと、このサイトの判定は全部信用できなくなる。
 */
export const FORBIDDEN_PHRASES = [
  "probably compatible",
  "should fit",
  "guaranteed compatible",
  "guaranteed to fit",
  "should work with",
  "likely compatible",
  "probably fits",
];

export const PRODUCT_STATUS_LABEL: Record<ProductStatus, string> = {
  current: "Current",
  discontinued: "Discontinued",
  unknown: UNKNOWN_LABEL,
};

/** 欠損値の表示。null / 空文字 / 空白のみ を Unknown に寄せる */
export function displayOrUnknown(value: string | null | undefined): string {
  if (typeof value !== "string") return UNKNOWN_LABEL;
  const trimmed = value.trim();
  return trimmed === "" ? UNKNOWN_LABEL : trimmed;
}

/**
 * 後継品の言い方。
 * **後継品があること自体は互換性の根拠にならない**ので、ここでは
 * 「現行の相当品が特定できている」までしか言わない。
 */
export function successorStatement(product: ProductRecord): EvidenceStatement {
  if (product.confirmedSuccessorId) return EVIDENCE_STATEMENTS.currentEquivalent;
  if (product.status === "discontinued")
    return EVIDENCE_STATEMENTS.discontinuedNoSuccessor;
  return EVIDENCE_STATEMENTS.insufficient;
}

/**
 * 後継品の行を表示するか。
 *
 * 現行品で後継品が無いのは**普通のこと**であって、根拠が足りないわけではない。
 * それを Insufficient evidence と書くと、確認不足のように読めて誤解を招く。
 * 判定表現を5つ目に増やすより、行そのものを出さないほうが正確。
 *
 * 廃番品と状態不明の商品では、後継品の有無が読者の関心そのものなので必ず出す。
 */
export function shouldShowSuccessor(product: ProductRecord): boolean {
  if (product.confirmedSuccessorId) return true;
  return product.status !== "current";
}

/** 互換性の言い方。confirmed 以外はすべて「根拠不足」に倒す */
export function compatibilityStatement(
  entry: CompatibilityRecord
): EvidenceStatement {
  return entry.status === "confirmed" && entry.sourceIds.length > 0
    ? EVIDENCE_STATEMENTS.confirmed
    : EVIDENCE_STATEMENTS.insufficient;
}

// ─── 正規化 ───────────────────────────────────────────

/**
 * 型番の正規化。次を吸収する:
 *   大文字・小文字         ck-080     → CK080
 *   ハイフンの有無         CK080      → CK080
 *   半角/全角スペース      CK - 080   → CK080
 *   前後の余分な空白       "  CK-080 " → CK080
 *   全角英数              ＣＫ－０８０ → CK080（NFKCで畳む）
 *
 * ハイフンごと落とすので "CK-080" と "CK080" は同じキーになる。
 * 型番はハイフンの有無が表記ゆれとして常に出るため、ここは同一視が正しい。
 */
export function normalizeModelNumber(input: string | null | undefined): string {
  if (typeof input !== "string") return "";
  return input
    .normalize("NFKC")
    .toUpperCase()
    // 半角ハイフン・全角ハイフン・各種ダッシュ・アンダースコアを落とす
    .replace(/[-‐‑‒–—―ー_]/g, "")
    // 空白（全角スペースはNFKCで半角になる）を落とす
    .replace(/\s+/g, "")
    .trim();
}

/** 商品名・aliasの正規化。語の区切りは残したいので空白は潰さず1つに畳む */
export function normalizeName(input: string | null | undefined): string {
  if (typeof input !== "string") return "";
  return input.normalize("NFKC").toLowerCase().replace(/\s+/g, " ").trim();
}

// ─── 検索 ─────────────────────────────────────────────

export type SearchMatchField =
  | "japaneseModelNumber"
  | "usModelNumber"
  | "alias"
  | "productName";

export type SearchMatch = {
  product: ProductRecord;
  matchedOn: SearchMatchField;
};

export type SearchResult =
  | { status: "empty" }
  | { status: "found"; matches: SearchMatch[] }
  | { status: "not_found"; query: string };

/**
 * 型番または商品名で引く。
 *
 * 優先順位は 型番の完全一致 → alias の完全一致 → 商品名の部分一致。
 * 型番を部分一致にしないのは、"CK-080" が "CK-0801" に前方一致して
 * 別品番を掴む事故を避けるため（同じ失敗を日本語側の型番照合で経験している）。
 */
export function searchProducts(
  rawQuery: string,
  products: ProductRecord[]
): SearchResult {
  const query = typeof rawQuery === "string" ? rawQuery.trim() : "";
  if (query === "") return { status: "empty" };

  const modelKey = normalizeModelNumber(query);
  const nameKey = normalizeName(query);
  const matches: SearchMatch[] = [];
  const seen = new Set<string>();

  const push = (product: ProductRecord, matchedOn: SearchMatchField) => {
    if (seen.has(product.id)) return;
    seen.add(product.id);
    matches.push({ product, matchedOn });
  };

  if (modelKey !== "") {
    for (const p of products) {
      if (normalizeModelNumber(p.japaneseModelNumber) === modelKey)
        push(p, "japaneseModelNumber");
    }
    for (const p of products) {
      if (normalizeModelNumber(p.usModelNumber) === modelKey)
        push(p, "usModelNumber");
    }
    // alias に型番が入っていることがある（旧表記など）
    for (const p of products) {
      if (p.aliases.some((a) => normalizeModelNumber(a) === modelKey))
        push(p, "alias");
    }
  }

  if (nameKey !== "") {
    for (const p of products) {
      if (p.aliases.some((a) => normalizeName(a) === nameKey)) push(p, "alias");
    }
    for (const p of products) {
      const name = normalizeName(p.productName);
      if (name === nameKey || name.includes(nameKey)) push(p, "productName");
    }
    for (const p of products) {
      if (p.aliases.some((a) => normalizeName(a).includes(nameKey)))
        push(p, "alias");
    }
  }

  if (matches.length === 0) return { status: "not_found", query };
  return { status: "found", matches };
}

// ─── バリデーション ───────────────────────────────────

const ISO_DATE = /^\d{4}-\d{2}-\d{2}(?:T[\d:.]+Z?)?$/;

function isNonEmptyString(v: unknown): v is string {
  return typeof v === "string" && v.trim() !== "";
}

/**
 * 出典レコードの検証。
 * 公式以外（掲示板・ショップ記事）は sourceType の型で弾かれる。
 */
export function validateSourceRecord(input: unknown): string[] {
  const errors: string[] = [];
  if (typeof input !== "object" || input === null) return ["source is not an object"];
  const s = input as Partial<SourceRecord>;

  if (!isNonEmptyString(s.id)) errors.push("source.id is required");
  if (!isNonEmptyString(s.publisher)) errors.push(`source(${s.id}).publisher is required`);
  if (!isNonEmptyString(s.title)) errors.push(`source(${s.id}).title is required`);
  if (!isNonEmptyString(s.url) || !/^https:\/\//.test(s.url ?? ""))
    errors.push(`source(${s.id}).url must be an absolute https URL`);
  const types: SourceType[] = [
    "official_product_page",
    "official_manual",
    "official_archive",
    "official_support",
  ];
  if (!types.includes(s.sourceType as SourceType))
    errors.push(`source(${s.id}).sourceType must be one of official_* types`);
  if (!isNonEmptyString(s.lastVerifiedAt) || !ISO_DATE.test(s.lastVerifiedAt ?? ""))
    errors.push(`source(${s.id}).lastVerifiedAt is required (YYYY-MM-DD)`);

  return errors;
}

/**
 * 商品レコードの検証。
 *
 * 本番データの絶対条件をここで守る:
 *   - 出典が必ず1件以上あり、実在する source を指している
 *   - 確認日がある
 *   - 互換性 confirmed には出典が要る（根拠なしのconfirmedを作らせない）
 *   - 後継品IDは実在する商品を指す
 */
export function validateProductRecord(
  input: unknown,
  knownSourceIds: Set<string>,
  knownProductIds?: Set<string>
): string[] {
  const errors: string[] = [];
  if (typeof input !== "object" || input === null) return ["product is not an object"];
  const p = input as Partial<ProductRecord>;
  const id = isNonEmptyString(p.id) ? p.id : "(no id)";

  if (!isNonEmptyString(p.id)) errors.push("product.id is required");
  if (!isNonEmptyString(p.productName)) errors.push(`product(${id}).productName is required`);
  if (!Array.isArray(p.aliases)) errors.push(`product(${id}).aliases must be an array`);

  const statuses: ProductStatus[] = ["current", "discontinued", "unknown"];
  if (!statuses.includes(p.status as ProductStatus))
    errors.push(`product(${id}).status must be current | discontinued | unknown`);

  // 出典と確認日は本番データの必須条件
  if (!Array.isArray(p.sourceIds) || p.sourceIds.length === 0) {
    errors.push(`product(${id}).sourceIds is required (at least one official source)`);
  } else {
    for (const sid of p.sourceIds) {
      if (!knownSourceIds.has(sid))
        errors.push(`product(${id}).sourceIds refers to unknown source "${sid}"`);
    }
  }
  if (!isNonEmptyString(p.lastVerifiedAt) || !ISO_DATE.test(p.lastVerifiedAt ?? ""))
    errors.push(`product(${id}).lastVerifiedAt is required (YYYY-MM-DD)`);

  if (!Array.isArray(p.compatibility)) {
    errors.push(`product(${id}).compatibility must be an array`);
  } else {
    for (const c of p.compatibility) {
      const compatStatuses: CompatibilityStatus[] = ["confirmed", "not_confirmed", "unknown"];
      if (!compatStatuses.includes(c?.status)) {
        errors.push(`product(${id}).compatibility.status is invalid`);
        continue;
      }
      // confirmed を名乗るなら出典が要る。ここを緩めると全体が信用できなくなる
      if (c.status === "confirmed" && (!Array.isArray(c.sourceIds) || c.sourceIds.length === 0))
        errors.push(
          `product(${id}).compatibility(${c.targetId}) is "confirmed" but has no sourceIds`
        );
      for (const sid of c.sourceIds ?? []) {
        if (!knownSourceIds.has(sid))
          errors.push(
            `product(${id}).compatibility(${c.targetId}) refers to unknown source "${sid}"`
          );
      }
      if (knownProductIds && isNonEmptyString(c.targetId) && !knownProductIds.has(c.targetId))
        errors.push(
          `product(${id}).compatibility refers to unknown product "${c.targetId}"`
        );
    }
  }

  if (p.confirmedSuccessorId != null) {
    if (!isNonEmptyString(p.confirmedSuccessorId))
      errors.push(`product(${id}).confirmedSuccessorId must be a string or null`);
    else if (knownProductIds && !knownProductIds.has(p.confirmedSuccessorId))
      errors.push(
        `product(${id}).confirmedSuccessorId refers to unknown product "${p.confirmedSuccessorId}"`
      );
  }

  if (!Array.isArray(p.purchaseOptions)) {
    errors.push(`product(${id}).purchaseOptions must be an array`);
  } else {
    for (const o of p.purchaseOptions) {
      const markets: Market[] = ["us", "jp", "other"];
      if (!markets.includes(o?.market)) errors.push(`product(${id}).purchaseOptions.market is invalid`);
      if (!isNonEmptyString(o?.merchant)) errors.push(`product(${id}).purchaseOptions.merchant is required`);
      if (!isNonEmptyString(o?.url) || !/^https:\/\//.test(o.url))
        errors.push(`product(${id}).purchaseOptions.url must be an absolute https URL`);
      if (typeof o?.affiliate !== "boolean")
        errors.push(`product(${id}).purchaseOptions.affiliate must be a boolean`);
    }
  }

  return errors;
}

/** データセット全体の検証。1件でも壊れていれば全部のエラーを返す */
export function validateDataset(
  products: unknown[],
  sources: unknown[]
): string[] {
  const errors: string[] = [];
  for (const s of sources) errors.push(...validateSourceRecord(s));

  const sourceIds = new Set(
    sources
      .filter((s): s is SourceRecord => typeof s === "object" && s !== null)
      .map((s) => s.id)
      .filter(isNonEmptyString)
  );
  const productIds = new Set(
    products
      .filter((p): p is ProductRecord => typeof p === "object" && p !== null)
      .map((p) => p.id)
      .filter(isNonEmptyString)
  );

  for (const p of products) errors.push(...validateProductRecord(p, sourceIds, productIds));
  return errors;
}
