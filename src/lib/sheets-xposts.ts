import { google } from "googleapis";
import { XPost } from "./types";

const SHEET_NAME = "下書き管理";
// カラムマッピング（generate-x-posts.js の書き込み順に準拠）:
// A=id, B=type, C=text, D=articleSlug, E=url, F=hashtags, G=status,
// H=scheduledDate, I=generatedAt, J=postedAt, K=axis, L=seedId,
// M=validationErrors, N=autoApproved, O=selfScore, P=firstLinePattern,
// Q=similarityScore, R=retryCount, S=imageUrl
const COLUMN_RANGE = "A2:S";

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

function rowToXPost(row: string[]): XPost {
  // K〜R列は既存行では undefined のことが多い → 後方互換
  return {
    id: row[0] || "",
    type: (row[1] as XPost["type"]) || "outdoor_tip",
    text: row[2] || "",
    articleSlug: row[3] || null,
    url: row[4] || null,
    hashtags: row[5] || "",
    status: (row[6] as XPost["status"]) || "draft",
    scheduledDate: row[7] || "",
    generatedAt: row[8] || "",
    postedAt: row[9] || null,
    axis: row[10] || undefined,
    seedId: row[11] || undefined,
    validationErrors: row[12] || undefined,
    autoApproved: row[13] || undefined,
    selfScore: row[14] ? parseFloat(row[14]) : undefined,
    firstLinePattern: row[15] || undefined,
    similarityScore: row[16] ? parseFloat(row[16]) : undefined,
    retryCount: row[17] ? parseInt(row[17], 10) : undefined,
    imageUrl: row[18] || undefined,
  };
}

function xpostToRow(post: XPost): string[] {
  return [
    post.id,
    post.type,
    post.text,
    post.articleSlug || "",
    post.url || "",
    post.hashtags || "",
    post.status,
    post.scheduledDate,
    post.generatedAt,
    post.postedAt || "",
    post.axis || "",
    post.seedId || "",
    post.validationErrors || "",
    post.autoApproved || "",
    post.selfScore != null ? String(post.selfScore) : "",
    post.firstLinePattern || "",
    post.similarityScore != null ? String(post.similarityScore) : "",
    post.retryCount != null ? String(post.retryCount) : "",
    post.imageUrl || "",
  ];
}

export async function getSheetsXPosts(): Promise<XPost[]> {
  const sheets = getSheets();
  const res = await sheets.spreadsheets.values.get({
    spreadsheetId: getSpreadsheetId(),
    range: `${SHEET_NAME}!${COLUMN_RANGE}`,
  });
  const rows = res.data.values || [];
  return rows
    .map(rowToXPost)
    .filter((p) => p.id)
    .sort(
      (a, b) =>
        new Date(b.generatedAt).getTime() - new Date(a.generatedAt).getTime()
    );
}

export async function getSheetsXPostById(
  id: string
): Promise<{ post: XPost; rowIndex: number } | null> {
  const sheets = getSheets();
  const res = await sheets.spreadsheets.values.get({
    spreadsheetId: getSpreadsheetId(),
    range: `${SHEET_NAME}!${COLUMN_RANGE}`,
  });
  const rows = res.data.values || [];
  for (let i = 0; i < rows.length; i++) {
    if (rows[i][0] === id) {
      return { post: rowToXPost(rows[i]), rowIndex: i + 2 };
    }
  }
  return null;
}

export async function getSheetsXPostsByStatus(
  status: XPost["status"]
): Promise<XPost[]> {
  const posts = await getSheetsXPosts();
  return posts.filter((p) => p.status === status);
}

export async function saveSheetsXPost(post: XPost): Promise<void> {
  const sheets = getSheets();
  const spreadsheetId = getSpreadsheetId();
  const existing = await getSheetsXPostById(post.id);

  if (existing) {
    await sheets.spreadsheets.values.update({
      spreadsheetId,
      range: `${SHEET_NAME}!A${existing.rowIndex}:S${existing.rowIndex}`,
      valueInputOption: "RAW",
      requestBody: { values: [xpostToRow(post)] },
    });
  } else {
    await sheets.spreadsheets.values.append({
      spreadsheetId,
      range: `${SHEET_NAME}!A:S`,
      valueInputOption: "RAW",
      insertDataOption: "INSERT_ROWS",
      requestBody: { values: [xpostToRow(post)] },
    });
  }
}

export async function saveSheetsXPosts(posts: XPost[]): Promise<void> {
  const sheets = getSheets();
  const spreadsheetId = getSpreadsheetId();

  const rows = posts.map(xpostToRow);
  await sheets.spreadsheets.values.append({
    spreadsheetId,
    range: `${SHEET_NAME}!A:S`,
    valueInputOption: "RAW",
    insertDataOption: "INSERT_ROWS",
    requestBody: { values: rows },
  });
}

export async function batchUpdateSheetsXPostStatus(
  ids: string[],
  status: XPost["status"]
): Promise<number> {
  const sheets = getSheets();
  const spreadsheetId = getSpreadsheetId();
  const res = await sheets.spreadsheets.values.get({
    spreadsheetId,
    range: `${SHEET_NAME}!${COLUMN_RANGE}`,
  });
  const rows = res.data.values || [];
  const idSet = new Set(ids);
  let count = 0;

  for (let i = 0; i < rows.length; i++) {
    if (idSet.has(rows[i][0])) {
      const rowIndex = i + 2;
      await sheets.spreadsheets.values.update({
        spreadsheetId,
        range: `${SHEET_NAME}!G${rowIndex}`,
        valueInputOption: "RAW",
        requestBody: { values: [[status]] },
      });
      count++;
    }
  }
  return count;
}

export async function batchDeleteSheetsXPosts(ids: string[]): Promise<number> {
  const sheets = getSheets();
  const spreadsheetId = getSpreadsheetId();

  const meta = await sheets.spreadsheets.get({ spreadsheetId });
  const sheet = meta.data.sheets?.find(
    (s) => s.properties?.title === SHEET_NAME
  );
  if (!sheet) return 0;

  const res = await sheets.spreadsheets.values.get({
    spreadsheetId,
    range: `${SHEET_NAME}!${COLUMN_RANGE}`,
  });
  const rows = res.data.values || [];
  const idSet = new Set(ids);

  // 対象行のインデ��クスを収集し、降順ソート（下から削除してインデックスずれ防止）
  const rowIndices: number[] = [];
  for (let i = 0; i < rows.length; i++) {
    if (idSet.has(rows[i][0])) {
      rowIndices.push(i + 1); // 0-indexed (ヘッダー行分は sheetId ベースなので +1)
    }
  }
  if (rowIndices.length === 0) return 0;

  rowIndices.sort((a, b) => b - a);

  await sheets.spreadsheets.batchUpdate({
    spreadsheetId,
    requestBody: {
      requests: rowIndices.map((idx) => ({
        deleteDimension: {
          range: {
            sheetId: sheet.properties?.sheetId,
            dimension: "ROWS",
            startIndex: idx,
            endIndex: idx + 1,
          },
        },
      })),
    },
  });

  return rowIndices.length;
}

export async function deleteSheetsXPost(id: string): Promise<void> {
  const sheets = getSheets();
  const spreadsheetId = getSpreadsheetId();

  const meta = await sheets.spreadsheets.get({ spreadsheetId });
  const sheet = meta.data.sheets?.find(
    (s) => s.properties?.title === SHEET_NAME
  );
  if (!sheet) return;

  const existing = await getSheetsXPostById(id);
  if (!existing) return;

  await sheets.spreadsheets.batchUpdate({
    spreadsheetId,
    requestBody: {
      requests: [
        {
          deleteDimension: {
            range: {
              sheetId: sheet.properties?.sheetId,
              dimension: "ROWS",
              startIndex: existing.rowIndex - 1,
              endIndex: existing.rowIndex,
            },
          },
        },
      ],
    },
  });
}
