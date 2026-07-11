import fs from "node:fs/promises";
import path from "node:path";
import { NextResponse } from "next/server";
import { isAuthenticated } from "@/lib/auth";

export const runtime = "nodejs";

// link-check（日曜6:30のlaunchdジョブ）が書き出すレポートを返す。
// 本番(Vercel)ではデプロイ時点にバンドルされたスナップショット、
// ローカルdevでは常に最新ファイルが読める。
const REPORT_PATH = path.join(process.cwd(), "data", "link-check-report.json");

export async function GET() {
  if (!(await isAuthenticated())) {
    return NextResponse.json({ error: "認証が必要です" }, { status: 401 });
  }
  try {
    const raw = await fs.readFile(REPORT_PATH, "utf8");
    return NextResponse.json({ exists: true, ...JSON.parse(raw) });
  } catch {
    return NextResponse.json({ exists: false });
  }
}
