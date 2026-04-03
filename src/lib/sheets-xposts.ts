import { google } from "googleapis";
import { XPost } from "./types";

const SHEET_NAME = "下書き管理";

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
  ];
}

export async function getSheetsXPosts(): Promise<XPost[]> {
  const sheets = getSheets();
  const res = await sheets.spreadsheets.values.get({
    spreadsheetId: getSpreadsheetId(),
    range: `${SHEET_NAME}!A2:J`,
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
    range: `${SHEET_NAME}!A2:J`,
  });
  const rows = res.data.values || [];
  for (let i = 0; i < rows.length; i++) {
    if (rows[i][0] === id) {
      return { post: rowToXPost(rows[i]), rowIndex: i + 2 }; // +2 for header row + 1-indexed
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
    // 既存行を更新
    await sheets.spreadsheets.values.update({
      spreadsheetId,
      range: `${SHEET_NAME}!A${existing.rowIndex}:J${existing.rowIndex}`,
      valueInputOption: "RAW",
      requestBody: { values: [xpostToRow(post)] },
    });
  } else {
    // 新規行を追加
    await sheets.spreadsheets.values.append({
      spreadsheetId,
      range: `${SHEET_NAME}!A:J`,
      valueInputOption: "RAW",
      requestBody: { values: [xpostToRow(post)] },
    });
  }
}

export async function saveSheetsXPosts(posts: XPost[]): Promise<void> {
  const sheets = getSheets();
  const spreadsheetId = getSpreadsheetId();

  // 新規投稿をまとめて追加
  const rows = posts.map(xpostToRow);
  await sheets.spreadsheets.values.append({
    spreadsheetId,
    range: `${SHEET_NAME}!A:J`,
    valueInputOption: "RAW",
    requestBody: { values: rows },
  });
}

export async function deleteSheetsXPost(id: string): Promise<void> {
  const sheets = getSheets();
  const spreadsheetId = getSpreadsheetId();

  // シートIDを取得
  const meta = await sheets.spreadsheets.get({ spreadsheetId });
  const sheet = meta.data.sheets?.find(
    (s) => s.properties?.title === SHEET_NAME
  );
  if (!sheet) return;

  const existing = await getSheetsXPostById(id);
  if (!existing) return;

  // 行を削除
  await sheets.spreadsheets.batchUpdate({
    spreadsheetId,
    requestBody: {
      requests: [
        {
          deleteDimension: {
            range: {
              sheetId: sheet.properties?.sheetId,
              dimension: "ROWS",
              startIndex: existing.rowIndex - 1, // 0-indexed
              endIndex: existing.rowIndex,
            },
          },
        },
      ],
    },
  });
}
