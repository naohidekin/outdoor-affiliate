import { NextRequest, NextResponse } from "next/server";
import { isAuthenticated } from "@/lib/auth";
import { google } from "googleapis";

const DRAFT_SHEET = "下書き管理";
const THREADS_BASE = "https://graph.threads.net/v1.0";

function getAuth() {
  const credentials = JSON.parse(process.env.GOOGLE_CREDENTIALS || "{}");
  return new google.auth.GoogleAuth({
    credentials,
    scopes: ["https://www.googleapis.com/auth/spreadsheets"],
  });
}

async function createContainer(userId: string, text: string, token: string): Promise<string> {
  const params = new URLSearchParams({ media_type: "TEXT", text, access_token: token });
  const res = await fetch(`${THREADS_BASE}/${userId}/threads?${params}`, { method: "POST" });
  const data = await res.json();
  if (data.error) throw new Error(`コンテナ作成エラー: ${data.error.message}`);
  if (!data.id) throw new Error(`Container ID なし: ${JSON.stringify(data)}`);
  return data.id;
}

async function waitForContainer(containerId: string, token: string): Promise<void> {
  for (let i = 0; i < 12; i++) {
    await new Promise((r) => setTimeout(r, 5000));
    const params = new URLSearchParams({ fields: "status,error_message", access_token: token });
    const res = await fetch(`${THREADS_BASE}/${containerId}?${params}`);
    const data = await res.json();
    if (data.status === "FINISHED") return;
    if (data.status === "ERROR") throw new Error(`Container ERROR: ${data.error_message}`);
    if (data.status === "EXPIRED") throw new Error("Container EXPIRED");
  }
  throw new Error("Container タイムアウト（60秒）");
}

async function publishContainer(userId: string, containerId: string, token: string): Promise<string> {
  const params = new URLSearchParams({ creation_id: containerId, access_token: token });
  const res = await fetch(`${THREADS_BASE}/${userId}/threads_publish?${params}`, { method: "POST" });
  const data = await res.json();
  if (data.error) throw new Error(`公開エラー: ${data.error.message}`);
  if (!data.id) throw new Error(`Post ID なし: ${JSON.stringify(data)}`);
  return data.id;
}

function buildThreadsText(text: string, sourceUrl: string | null): string {
  let t = text.trim();
  if (sourceUrl && !t.includes(sourceUrl)) {
    const withUrl = `${t}\n\n${sourceUrl}`;
    if (withUrl.length <= 500) t = withUrl;
  }
  return t.length > 500 ? t.slice(0, 497) + "..." : t;
}

export async function POST(req: NextRequest) {
  if (!(await isAuthenticated())) {
    return NextResponse.json({ error: "認証が必要です" }, { status: 401 });
  }

  const userId = process.env.THREADS_USER_ID;
  const accessToken = process.env.THREADS_ACCESS_TOKEN;
  const username = process.env.THREADS_USERNAME || "camp_gear_lab";

  if (!userId || !accessToken) {
    return NextResponse.json(
      { error: "THREADS_USER_ID / THREADS_ACCESS_TOKEN が .env.local に未設定です" },
      { status: 503 }
    );
  }

  const body = await req.json().catch(() => ({}));
  const targetId: string | undefined = body.id;

  try {
    const sheets = google.sheets({ version: "v4", auth: getAuth() });
    const spreadsheetId = process.env.X_SHEET_ID!;
    const res = await sheets.spreadsheets.values.get({
      spreadsheetId,
      range: `${DRAFT_SHEET}!A2:W`,
    });
    const rows = res.data.values || [];

    // 対象行を特定
    const rowEntry = rows
      .map((row, i) => ({ row, rowIndex: i + 2 }))
      .filter(({ row }) => {
        const status = row[6] || "";
        const threadsStatus = row[21] || "";
        const eligible = (status === "queued" || status === "posted") && !threadsStatus;
        if (targetId) return eligible && row[0] === targetId;
        return eligible;
      })[0];

    if (!rowEntry) {
      return NextResponse.json({ error: "投稿対象がありません" }, { status: 404 });
    }

    const { row, rowIndex } = rowEntry;
    const text = row[2] || "";
    const sourceUrl = row[4] || null;
    const threadsText = buildThreadsText(text, sourceUrl);

    // Threads API 2ステップ投稿
    const containerId = await createContainer(userId, threadsText, accessToken);
    await waitForContainer(containerId, accessToken);
    const postId = await publishContainer(userId, containerId, accessToken);
    const postUrl = `https://www.threads.net/@${username}/post/${postId}`;

    // Sheets 更新（V列: threads_status, W列: threads_post_url）
    await sheets.spreadsheets.values.update({
      spreadsheetId,
      range: `${DRAFT_SHEET}!V${rowIndex}:W${rowIndex}`,
      valueInputOption: "RAW",
      requestBody: { values: [["posted", postUrl]] },
    });

    return NextResponse.json({ ok: true, postUrl, text: threadsText });
  } catch (e) {
    const msg = e instanceof Error ? e.message : String(e);
    console.error("threads-posts run error:", msg);
    return NextResponse.json({ error: msg }, { status: 500 });
  }
}
