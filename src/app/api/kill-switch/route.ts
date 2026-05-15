import fs from "node:fs/promises";
import path from "node:path";
import { NextRequest, NextResponse } from "next/server";
import { isAuthenticatedRequest } from "@/lib/auth";

export const runtime = "nodejs";

const KILL_SWITCH_PATH = path.join(process.env.HOME || "", ".claude/context/kill_switch.json");

type BusinessName = "gearman" | "amble" | "kodomo";
type PlatformName = "x" | "article" | "research" | "note" | "threads";

type KillSwitchState = {
  businesses: {
    gearman: {
      x: boolean;
      article: boolean;
      research: boolean;
    };
    amble: {
      x: boolean;
    };
    kodomo: {
      x: boolean;
      note: boolean;
      threads: boolean;
    };
  };
  global: boolean;
  updatedAt: string;
  reason: string;
};

type KillSwitchPostBody =
  | {
      business: BusinessName;
      platform: PlatformName;
      value: boolean;
      reason?: string;
      global?: never;
    }
  | {
      global: boolean;
      reason?: string;
      business?: never;
      platform?: never;
      value?: never;
    };

const DEFAULT_STATE: KillSwitchState = {
  businesses: {
    gearman: { x: false, article: false, research: false },
    amble: { x: false },
    kodomo: { x: false, note: false, threads: false },
  },
  global: false,
  updatedAt: "",
  reason: "",
};

function jstTimestamp() {
  return new Date().toLocaleString("sv-SE", { timeZone: "Asia/Tokyo" }).replace(" ", "T") + "+09:00";
}

function normalizeState(input: Partial<KillSwitchState> | undefined): KillSwitchState {
  return {
    ...DEFAULT_STATE,
    ...input,
    businesses: {
      gearman: {
        ...DEFAULT_STATE.businesses.gearman,
        ...input?.businesses?.gearman,
      },
      amble: {
        ...DEFAULT_STATE.businesses.amble,
        ...input?.businesses?.amble,
      },
      kodomo: {
        ...DEFAULT_STATE.businesses.kodomo,
        ...input?.businesses?.kodomo,
      },
    },
  };
}

async function readKillSwitch(): Promise<KillSwitchState> {
  try {
    const raw = await fs.readFile(KILL_SWITCH_PATH, "utf8");
    return normalizeState(JSON.parse(raw) as Partial<KillSwitchState>);
  } catch {
    return DEFAULT_STATE;
  }
}

async function writeKillSwitch(state: KillSwitchState) {
  await fs.mkdir(path.dirname(KILL_SWITCH_PATH), { recursive: true });
  await fs.writeFile(KILL_SWITCH_PATH, `${JSON.stringify(state, null, 2)}\n`, "utf8");
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
    const body = (await req.json()) as Partial<KillSwitchPostBody>;
    const hasBusinessUpdate =
      typeof body.business === "string" &&
      typeof body.platform === "string" &&
      typeof body.value === "boolean";
    const hasGlobalUpdate = typeof body.global === "boolean";

    if (!hasBusinessUpdate && !hasGlobalUpdate) {
      return NextResponse.json(
        { error: "business/platform/value または global が必要です" },
        { status: 400 },
      );
    }

    const current = await readKillSwitch();
    const nextState = normalizeState({
      ...current,
      global: hasGlobalUpdate ? body.global : current.global,
      updatedAt: jstTimestamp(),
      reason: typeof body.reason === "string" ? body.reason : current.reason,
    });

    if (hasBusinessUpdate) {
      const business = body.business as BusinessName;
      const platform = body.platform as PlatformName;
      const businessState = nextState.businesses[business] as Record<string, boolean>;
      if (!(platform in businessState)) {
        return NextResponse.json(
          { error: "business と platform の組み合わせが不正です" },
          { status: 400 },
        );
      }
      businessState[platform] = body.value as boolean;
    }

    await writeKillSwitch(nextState);
    return NextResponse.json(nextState);
  } catch (error) {
    console.error("Kill switch POST error:", error);
    return NextResponse.json({ error: "更新に失敗しました" }, { status: 500 });
  }
}
