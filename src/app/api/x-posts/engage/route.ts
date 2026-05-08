import { NextRequest, NextResponse } from "next/server";
import { google } from "googleapis";
import { isAuthenticated } from "@/lib/auth";

const ENGAGE_SHEET = "エンゲージ管理";

// スキーマ: status | postType | text | imageUrl | sourceUrl | scheduledAt | postedAt | postUrl | _ | targetTweetId

export interface EngagePost {
  rowIndex: number;
  status: string;
  postType: string;
  text: string;
  imageUrl: string;
  sourceUrl: string;
  scheduledAt: string;
  postedAt: string;
  postUrl: string;
  targetTweetId: string;
}

function getSheets() {
  const credentials = JSON.parse(process.env.GOOGLE_CREDENTIALS || "{}");
  const auth = new google.auth.GoogleAuth({
    credentials,
    scopes: ["https://www.googleapis.com/auth/spreadsheets"],
  });
  return google.sheets({ version: "v4", auth });
}

function getSpreadsheetId(): string {
  const id = process.env.X_SHEET_ID;
  if (!id) throw new Error("X_SHEET_ID が設定されていません");
  return id;
}

function rowToEngagePost(row: string[], rowIndex: number): EngagePost {
  return {
    rowIndex,
    status: row[0] || "",
    postType: row[1] || "quote",
    text: row[2] || "",
    imageUrl: row[3] || "",
    sourceUrl: row[4] || "",
    scheduledAt: row[5] || "",
    postedAt: row[6] || "",
    postUrl: row[7] || "",
    targetTweetId: row[9] || "",
  };
}

// GET: pending / ready 行を取得
export async function GET() {
  if (!(await isAuthenticated())) {
    return NextResponse.json({ error: "認証が必要です" }, { status: 401 });
  }

  try {
    const sheets = getSheets();
    const spreadsheetId = getSpreadsheetId();

    const res = await sheets.spreadsheets.values.get({
      spreadsheetId,
      range: `${ENGAGE_SHEET}!A2:J`,
    });

    const rows = res.data.values || [];
    const posts: EngagePost[] = [];

    for (let i = 0; i < rows.length; i++) {
      const row = rows[i];
      const status = row[0] || "";
      if (status === "pending" || status === "ready") {
        posts.push(rowToEngagePost(row, i + 2));
      }
    }

    return NextResponse.json(posts);
  } catch (e) {
    console.error("engage GET error:", e);
    return NextResponse.json({ error: "データ取得に失敗しました" }, { status: 500 });
  }
}

// PATCH: rowIndex の status を更新（ready または skipped）
export async function PATCH(req: NextRequest) {
  if (!(await isAuthenticated())) {
    return NextResponse.json({ error: "認証が必要です" }, { status: 401 });
  }

  const body = await req.json();
  const { rowIndex, status } = body as { rowIndex: number; status: string };

  if (!rowIndex || !["ready", "skipped"].includes(status)) {
    return NextResponse.json({ error: "rowIndex と status (ready|skipped) が必要です" }, { status: 400 });
  }

  try {
    const sheets = getSheets();
    const spreadsheetId = getSpreadsheetId();

    await sheets.spreadsheets.values.update({
      spreadsheetId,
      range: `${ENGAGE_SHEET}!A${rowIndex}`,
      valueInputOption: "RAW",
      requestBody: { values: [[status]] },
    });

    return NextResponse.json({ ok: true });
  } catch (e) {
    console.error("engage PATCH error:", e);
    return NextResponse.json({ error: "更新に失敗しました" }, { status: 500 });
  }
}
