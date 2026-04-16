import { NextRequest, NextResponse } from "next/server";
import { google } from "googleapis";
import { isAuthenticated } from "@/lib/auth";
import { getSheetsXPostById, saveSheetsXPost } from "@/lib/sheets-xposts";

const QUEUE_SHEET = "X投稿管理";

function getAuth() {
  const credentials = JSON.parse(process.env.GOOGLE_CREDENTIALS || "{}");
  return new google.auth.GoogleAuth({
    credentials,
    scopes: ["https://www.googleapis.com/auth/spreadsheets"],
  });
}

export async function POST(req: NextRequest) {
  if (!(await isAuthenticated())) {
    return NextResponse.json({ error: "認証が必要です" }, { status: 401 });
  }

  const { id } = await req.json();
  if (!id) {
    return NextResponse.json({ error: "id required" }, { status: 400 });
  }

  const result = await getSheetsXPostById(id);
  if (!result) {
    return NextResponse.json({ error: "投稿が見つかりません" }, { status: 404 });
  }

  const { post } = result;

  if (post.status === "posted" || post.status === "queued") {
    return NextResponse.json(
      { error: "この投稿は既にキュー済みまたは投稿済みです" },
      { status: 400 }
    );
  }

  const sheets = google.sheets({ version: "v4", auth: getAuth() });
  const spreadsheetId = process.env.X_SHEET_ID!;

  // X投稿管理シートにヘッダーがなければ作成
  try {
    const existing = await sheets.spreadsheets.values.get({
      spreadsheetId,
      range: `${QUEUE_SHEET}!A1:H1`,
    });
    if (!existing.data.values || existing.data.values.length === 0) {
      await sheets.spreadsheets.values.update({
        spreadsheetId,
        range: `${QUEUE_SHEET}!A1:H1`,
        valueInputOption: "RAW",
        requestBody: {
          values: [["status", "post_type", "text", "image_url", "source_url", "scheduled_at", "posted_at", "post_url"]],
        },
      });
    }
  } catch (err: unknown) {
    const error = err as { code?: number; message?: string };
    if (error.code === 400 || error.message?.includes("Unable to parse range")) {
      await sheets.spreadsheets.batchUpdate({
        spreadsheetId,
        requestBody: {
          requests: [{ addSheet: { properties: { title: QUEUE_SHEET } } }],
        },
      });
      await sheets.spreadsheets.values.update({
        spreadsheetId,
        range: `${QUEUE_SHEET}!A1:H1`,
        valueInputOption: "RAW",
        requestBody: {
          values: [["status", "post_type", "text", "image_url", "source_url", "scheduled_at", "posted_at", "post_url"]],
        },
      });
    } else {
      throw err;
    }
  }

  // X投稿管理シートに行を追加
  const sourceUrl = post.url || (post.articleSlug ? `https://camp-gear-lab.com/articles/${post.articleSlug}` : "");
  await sheets.spreadsheets.values.append({
    spreadsheetId,
    range: `${QUEUE_SHEET}!A:H`,
    valueInputOption: "RAW",
    requestBody: {
      values: [["ready", post.type, post.text, "", sourceUrl, new Date().toISOString().slice(0, 10), "", ""]],
    },
  });

  // 下書き管理のステータスをqueuedに更新
  const updated = { ...post, status: "queued" as const };
  await saveSheetsXPost(updated);

  return NextResponse.json(updated);
}
