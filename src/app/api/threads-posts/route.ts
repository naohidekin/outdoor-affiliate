import { NextResponse } from "next/server";
import { isAuthenticated } from "@/lib/auth";
import { google } from "googleapis";

const DRAFT_SHEET = "下書き管理";

function getAuth() {
  const credentials = JSON.parse(process.env.GOOGLE_CREDENTIALS || "{}");
  return new google.auth.GoogleAuth({
    credentials,
    scopes: ["https://www.googleapis.com/auth/spreadsheets"],
  });
}

export interface ThreadsPost {
  id: string;
  rowIndex: number;
  type: string;
  text: string;
  url: string | null;
  status: string;
  postedAt: string | null;
  threadsStatus: string;
  threadsPostUrl: string | null;
}

export async function GET() {
  if (!(await isAuthenticated())) {
    return NextResponse.json({ error: "認証が必要です" }, { status: 401 });
  }

  try {
    const sheets = google.sheets({ version: "v4", auth: getAuth() });
    const spreadsheetId = process.env.X_SHEET_ID!;
    const res = await sheets.spreadsheets.values.get({
      spreadsheetId,
      range: `${DRAFT_SHEET}!A2:W`,
    });

    const rows = res.data.values || [];
    const posts: ThreadsPost[] = rows
      .map((row, i) => ({
        id: row[0] || `row-${i + 2}`,
        rowIndex: i + 2,
        type: row[1] || "",
        text: row[2] || "",
        url: row[4] || null,
        status: row[6] || "",
        postedAt: row[9] || null,
        threadsStatus: row[21] || "",
        threadsPostUrl: row[22] || null,
      }))
      .filter((p) => p.status === "queued" || p.status === "posted");

    return NextResponse.json(posts);
  } catch (e) {
    console.error("threads-posts GET error:", e);
    return NextResponse.json({ error: "取得に失敗しました" }, { status: 500 });
  }
}
