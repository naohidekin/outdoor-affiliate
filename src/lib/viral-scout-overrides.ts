import { google } from "googleapis";

/**
 * Viral Scout のユーザー状態（削除・投稿済み等）を Google Sheets に永続化する。
 *
 * Vercel の serverless 環境ではファイル書き込みができないため、
 * data/viral-scout-results.json は「基礎データ」として読み取り専用で扱い、
 * ユーザー操作（削除・投稿済み・スキップ）は別シートに overrides として保存する。
 *
 * シート構成: タブ名 "Viralオーバーライド"
 *   A: tweetId         (主キー)
 *   B: deleted         ("true" or 空)
 *   C: quoteStatus     (posted / skipped / approved / needs_review / 空=draft)
 *   D: quotePostedAt   (ISO 文字列 or 空)
 *   E: replyStatus
 *   F: replyPostedAt
 *   G: updatedAt       (最終更新時刻 ISO)
 */

const SHEET_NAME = "Viralオーバーライド";
const HEADER = [
  "tweetId",
  "deleted",
  "quoteStatus",
  "quotePostedAt",
  "replyStatus",
  "replyPostedAt",
  "updatedAt",
];

export interface ViralOverride {
  tweetId: string;
  deleted: boolean;
  quoteStatus?: string;
  quotePostedAt?: string;
  replyStatus?: string;
  replyPostedAt?: string;
  updatedAt: string;
}

function getAuth() {
  const credentials = JSON.parse(process.env.GOOGLE_CREDENTIALS || "{}");
  return new google.auth.GoogleAuth({
    credentials,
    scopes: ["https://www.googleapis.com/auth/spreadsheets"],
  });
}

function getSheets() {
  return google.sheets({ version: "v4", auth: getAuth() });
}

function getSpreadsheetId(): string {
  const id = process.env.X_SHEET_ID;
  if (!id) throw new Error("X_SHEET_ID が設定されていません");
  return id;
}

/**
 * シートタブが無ければ作成してヘッダー行を書き込む。初回アクセス時のみ走る。
 */
async function ensureSheet(): Promise<number> {
  const sheets = getSheets();
  const spreadsheetId = getSpreadsheetId();
  const meta = await sheets.spreadsheets.get({ spreadsheetId });
  const existing = meta.data.sheets?.find(
    (s) => s.properties?.title === SHEET_NAME
  );
  if (existing) return existing.properties!.sheetId!;

  // 新規作成
  const add = await sheets.spreadsheets.batchUpdate({
    spreadsheetId,
    requestBody: {
      requests: [
        {
          addSheet: {
            properties: { title: SHEET_NAME, gridProperties: { rowCount: 500, columnCount: 10 } },
          },
        },
      ],
    },
  });
  const sheetId = add.data.replies?.[0]?.addSheet?.properties?.sheetId;
  // ヘッダー書き込み
  await sheets.spreadsheets.values.update({
    spreadsheetId,
    range: `${SHEET_NAME}!A1:G1`,
    valueInputOption: "RAW",
    requestBody: { values: [HEADER] },
  });
  return sheetId ?? 0;
}

/**
 * 現在の全 overrides を tweetId → ViralOverride の Map で取得。
 */
export async function getOverrides(): Promise<Map<string, ViralOverride>> {
  await ensureSheet();
  const sheets = getSheets();
  const spreadsheetId = getSpreadsheetId();
  const res = await sheets.spreadsheets.values.get({
    spreadsheetId,
    range: `${SHEET_NAME}!A2:G`,
  });
  const rows = res.data.values || [];
  const map = new Map<string, ViralOverride>();
  for (const row of rows) {
    const tweetId = row[0];
    if (!tweetId) continue;
    map.set(tweetId, {
      tweetId,
      deleted: row[1] === "true",
      quoteStatus: row[2] || undefined,
      quotePostedAt: row[3] || undefined,
      replyStatus: row[4] || undefined,
      replyPostedAt: row[5] || undefined,
      updatedAt: row[6] || "",
    });
  }
  return map;
}

/**
 * 該当 tweetId の override をパッチ更新（既存行は更新、無ければ追記）。
 * 複数件を一度に更新する場合は upsertManyOverrides を使う。
 */
export async function upsertOverride(
  tweetId: string,
  patch: Partial<Omit<ViralOverride, "tweetId" | "updatedAt">>
): Promise<void> {
  await upsertManyOverrides([{ tweetId, patch }]);
}

/**
 * 複数の tweetId を一括 upsert。削除や status一括更新で使う。
 */
export async function upsertManyOverrides(
  items: Array<{
    tweetId: string;
    patch: Partial<Omit<ViralOverride, "tweetId" | "updatedAt">>;
  }>
): Promise<void> {
  if (items.length === 0) return;
  await ensureSheet();
  const sheets = getSheets();
  const spreadsheetId = getSpreadsheetId();

  // 現在の全行を取得して既存行のインデックス(row番号)を把握
  const res = await sheets.spreadsheets.values.get({
    spreadsheetId,
    range: `${SHEET_NAME}!A2:G`,
  });
  const existingRows = res.data.values || [];
  const indexById = new Map<string, number>();
  existingRows.forEach((row, i) => {
    const id = row[0];
    if (id) indexById.set(id, i + 2); // シート上の実行番号
  });

  const now = new Date().toISOString();
  const updates: Array<{ range: string; values: string[][] }> = [];
  const appends: string[][] = [];

  for (const { tweetId, patch } of items) {
    const existingRow = indexById.has(tweetId)
      ? existingRows[indexById.get(tweetId)! - 2]
      : null;
    const merged: ViralOverride = {
      tweetId,
      deleted: patch.deleted ?? (existingRow?.[1] === "true"),
      quoteStatus: patch.quoteStatus ?? existingRow?.[2] ?? undefined,
      quotePostedAt: patch.quotePostedAt ?? existingRow?.[3] ?? undefined,
      replyStatus: patch.replyStatus ?? existingRow?.[4] ?? undefined,
      replyPostedAt: patch.replyPostedAt ?? existingRow?.[5] ?? undefined,
      updatedAt: now,
    };
    const values = [
      merged.tweetId,
      merged.deleted ? "true" : "",
      merged.quoteStatus || "",
      merged.quotePostedAt || "",
      merged.replyStatus || "",
      merged.replyPostedAt || "",
      merged.updatedAt,
    ];
    const rowIndex = indexById.get(tweetId);
    if (rowIndex !== undefined) {
      updates.push({
        range: `${SHEET_NAME}!A${rowIndex}:G${rowIndex}`,
        values: [values],
      });
    } else {
      appends.push(values);
    }
  }

  // 既存行は個別 update、新規行は一括 append
  if (updates.length > 0) {
    await sheets.spreadsheets.values.batchUpdate({
      spreadsheetId,
      requestBody: {
        valueInputOption: "RAW",
        data: updates,
      },
    });
  }
  if (appends.length > 0) {
    await sheets.spreadsheets.values.append({
      spreadsheetId,
      range: `${SHEET_NAME}!A:G`,
      valueInputOption: "RAW",
      requestBody: { values: appends },
    });
  }
}

/**
 * 複数 tweetId を「削除済み」としてマーク（ファイルからは実際には消さない）。
 * overrides を読む側で deleted=true の行を除外する。
 */
export async function markDeleted(tweetIds: string[]): Promise<void> {
  await upsertManyOverrides(
    tweetIds.map((tweetId) => ({ tweetId, patch: { deleted: true } }))
  );
}

/**
 * tweetId の quoteTweet または reply の status/postedAt を更新。
 */
export async function setStatus(
  tweetId: string,
  field: "quoteTweet" | "reply",
  status: string,
  postedAt?: string
): Promise<void> {
  const patch: Partial<Omit<ViralOverride, "tweetId" | "updatedAt">> = {};
  if (field === "quoteTweet") {
    patch.quoteStatus = status;
    patch.quotePostedAt = postedAt || "";
  } else {
    patch.replyStatus = status;
    patch.replyPostedAt = postedAt || "";
  }
  await upsertOverride(tweetId, patch);
}
