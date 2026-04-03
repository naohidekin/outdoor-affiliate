import { NextRequest, NextResponse } from "next/server";
import fs from "fs";
import path from "path";

const DATA_DIR = path.join(process.cwd(), "data");
const CLICKS_FILE = path.join(DATA_DIR, "affiliate-clicks.json");

interface ClickEvent {
  productId: string;
  store: string;
  path: string;
  timestamp: string;
}

export async function POST(req: NextRequest) {
  try {
    const body: ClickEvent = await req.json();

    if (!body.productId || !body.store) {
      return NextResponse.json({ error: "invalid" }, { status: 400 });
    }

    const entry = {
      productId: body.productId,
      store: body.store,
      path: body.path || "",
      timestamp: body.timestamp || new Date().toISOString(),
      ip: req.headers.get("x-forwarded-for")?.split(",")[0]?.trim() || "",
      ua: req.headers.get("user-agent")?.slice(0, 100) || "",
    };

    let clicks: unknown[] = [];
    if (fs.existsSync(CLICKS_FILE)) {
      clicks = JSON.parse(fs.readFileSync(CLICKS_FILE, "utf-8"));
    }
    clicks.push(entry);

    // 直近30日分のみ保持
    const thirtyDaysAgo = new Date(
      Date.now() - 30 * 24 * 60 * 60 * 1000
    ).toISOString();
    clicks = clicks.filter(
      (c: unknown) => (c as { timestamp: string }).timestamp > thirtyDaysAgo
    );

    fs.writeFileSync(CLICKS_FILE, JSON.stringify(clicks, null, 2));

    return NextResponse.json({ ok: true });
  } catch {
    return NextResponse.json({ error: "failed" }, { status: 500 });
  }
}
