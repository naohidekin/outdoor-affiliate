import fs from "node:fs/promises";
import path from "node:path";
import { NextRequest, NextResponse } from "next/server";
import { isAuthenticated } from "@/lib/auth";

export const runtime = "nodejs";

// ─────────────────────────────────────────────────────────────
// Kill Switch 一本化（2026-07-11 棚卸監査・案A）
// 正: data/kill-switch.json（このリポジトリ内。全パイプラインが参照）
// 旧: ~/.claude/context/kill_switch.json は廃止（現役の読み手なし）
//
// 意味論（歴史的経緯で「true = 停止」なので注意）:
//   enabled=true         → 全システム停止
//   articleEnabled=true  → 記事パイプラインのみ停止
//   researchEnabled=true → リサーチ系のみ停止
//   business.<name>=true → その事業のSNS投稿のみ停止（notion-posterがDB別に参照）
//
// 注意: Vercel本番のファイルシステムは読み取り専用のため、
// このスイッチの操作は「ローカルMacの dev 管理画面」専用。
// ─────────────────────────────────────────────────────────────

const KILL_SWITCH_PATH = path.join(process.cwd(), "data", "kill-switch.json");

const BUSINESS_NAMES = ["gearman", "amble", "kodomo", "jsh", "drAuto"] as const;
type BusinessName = (typeof BUSINESS_NAMES)[number];

type KillSwitchState = {
  enabled: boolean;
  articleEnabled: boolean;
  researchEnabled: boolean;
  business: Record<BusinessName, boolean>;
  reason: string;
  disabledAt: string;
  disabledBy: string;
  consecutiveErrors?: unknown[];
};

const DEFAULT_BUSINESS: Record<BusinessName, boolean> = {
  gearman: false,
  amble: false,
  kodomo: false,
  jsh: false,
  drAuto: false,
};

function jstTimestamp() {
  return new Date().toLocaleString("sv-SE", { timeZone: "Asia/Tokyo" }).replace(" ", "T") + "+09:00";
}

function normalize(input: Partial<KillSwitchState> | undefined): KillSwitchState {
  return {
    enabled: Boolean(input?.enabled),
    articleEnabled: Boolean(input?.articleEnabled),
    researchEnabled: Boolean(input?.researchEnabled),
    business: { ...DEFAULT_BUSINESS, ...(input?.business || {}) },
    reason: input?.reason || "",
    disabledAt: input?.disabledAt || "",
    disabledBy: input?.disabledBy || "",
    consecutiveErrors: input?.consecutiveErrors || [],
  };
}

async function readState(): Promise<KillSwitchState> {
  try {
    const raw = await fs.readFile(KILL_SWITCH_PATH, "utf8");
    return normalize(JSON.parse(raw) as Partial<KillSwitchState>);
  } catch {
    return normalize(undefined);
  }
}

export async function GET() {
  if (!(await isAuthenticated())) {
    return NextResponse.json({ error: "認証が必要です" }, { status: 401 });
  }
  return NextResponse.json(await readState());
}

type PostBody = {
  field?: "enabled" | "articleEnabled" | "researchEnabled";
  business?: BusinessName;
  value?: boolean;
  reason?: string;
};

export async function POST(req: NextRequest) {
  if (!(await isAuthenticated())) {
    return NextResponse.json({ error: "認証が必要です" }, { status: 401 });
  }

  let body: PostBody;
  try {
    body = (await req.json()) as PostBody;
  } catch {
    return NextResponse.json({ error: "不正なリクエスト" }, { status: 400 });
  }

  const isFieldUpdate =
    body.field !== undefined &&
    ["enabled", "articleEnabled", "researchEnabled"].includes(body.field) &&
    typeof body.value === "boolean";
  const isBusinessUpdate =
    body.business !== undefined &&
    (BUSINESS_NAMES as readonly string[]).includes(body.business) &&
    typeof body.value === "boolean";

  if (!isFieldUpdate && !isBusinessUpdate) {
    return NextResponse.json(
      { error: "field+value または business+value が必要です" },
      { status: 400 },
    );
  }

  const current = await readState();
  const next: KillSwitchState = {
    ...current,
    reason: typeof body.reason === "string" ? body.reason : current.reason,
    disabledAt: jstTimestamp(),
    disabledBy: "admin-ui",
  };
  if (isFieldUpdate) {
    next[body.field as "enabled" | "articleEnabled" | "researchEnabled"] = body.value as boolean;
  }
  if (isBusinessUpdate) {
    next.business = { ...current.business, [body.business as BusinessName]: body.value as boolean };
  }

  try {
    await fs.writeFile(KILL_SWITCH_PATH, `${JSON.stringify(next, null, 2)}\n`, "utf8");
  } catch {
    return NextResponse.json(
      { error: "書き込みに失敗しました。このスイッチはローカルMacのdev環境専用です（Vercel本番のファイルシステムは読み取り専用）。" },
      { status: 500 },
    );
  }

  return NextResponse.json(next);
}
