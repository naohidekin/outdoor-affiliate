import fs from "node:fs/promises";
import path from "node:path";
import { NextRequest, NextResponse } from "next/server";
import { isAuthenticatedRequest } from "@/lib/auth";

export const runtime = "nodejs";

const KILL_SWITCH_PATH = path.join(process.cwd(), "data", "kill-switch.json");

type KillSwitchState = {
  enabled?: boolean;
  articleEnabled?: boolean;
  researchEnabled?: boolean;
  reason?: string;
  lastUpdated?: string;
  lastReason?: string;
  [key: string]: unknown;
};

async function readKillSwitch(): Promise<KillSwitchState> {
  const raw = await fs.readFile(KILL_SWITCH_PATH, "utf8");
  return JSON.parse(raw) as KillSwitchState;
}

export async function GET(req: NextRequest) {
  if (!isAuthenticatedRequest(req)) {
    return NextResponse.json({ error: "認証が必要です" }, { status: 401 });
  }

  try {
    const state = await readKillSwitch();
    return NextResponse.json(state);
  } catch (error) {
    console.error("Kill switch GET error:", error);
    return NextResponse.json({ error: "データ取得に失敗しました" }, { status: 500 });
  }
}

export async function POST(req: NextRequest) {
  if (!isAuthenticatedRequest(req)) {
    return NextResponse.json({ error: "認証が必要です" }, { status: 401 });
  }

  try {
    const body = (await req.json()) as {
      field?: "enabled" | "articleEnabled" | "researchEnabled";
      value?: boolean;
      reason?: string;
    };
    if (!body.field || typeof body.value !== "boolean") {
      return NextResponse.json({ error: "field と value が必要です" }, { status: 400 });
    }

    const current = await readKillSwitch();
    const nextState: KillSwitchState = {
      ...current,
      [body.field]: body.value,
      lastUpdated: new Date().toISOString(),
      lastReason: body.reason || current.lastReason || current.reason || "",
      ...(body.reason ? { reason: body.reason } : {}),
    };

    await fs.writeFile(KILL_SWITCH_PATH, `${JSON.stringify(nextState, null, 2)}\n`, "utf8");
    return NextResponse.json(nextState);
  } catch (error) {
    console.error("Kill switch POST error:", error);
    return NextResponse.json({ error: "更新に失敗しました" }, { status: 500 });
  }
}
