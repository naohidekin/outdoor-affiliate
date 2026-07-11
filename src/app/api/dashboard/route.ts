import fs from "node:fs/promises";
import path from "node:path";
import { NextResponse } from "next/server";
import { isAuthenticated } from "@/lib/auth";

export const runtime = "nodejs";

// gearman（camp-gear-lab）専用ホーム。
// 旧マルチ事業カード（アンブロ/こどもケアラボ）は本番で恒常0だったため削除
// （各事業の管理はそれぞれのリポジトリ/Notionで行う。2026-07-11 棚卸監査の決定）。
const GEARMAN_QUEUE_PATH = path.join(process.cwd(), "data", "post-queue.json");
const KILL_SWITCH_PATH = path.join(process.cwd(), "data", "kill-switch.json");

type GearmanQueueItem = { status?: string };
type KillSwitchFile = {
  enabled?: boolean;
  articleEnabled?: boolean;
  researchEnabled?: boolean;
  reason?: string;
};

async function getGearmanReadyCount(): Promise<number> {
  try {
    const raw = await fs.readFile(GEARMAN_QUEUE_PATH, "utf8");
    const data = JSON.parse(raw) as { queue?: GearmanQueueItem[] };
    return (data.queue || []).filter((item) => item.status === "ready").length;
  } catch {
    return 0;
  }
}

async function getKillSwitch(): Promise<{ enabled: boolean; articleStopped: boolean; reason: string }> {
  try {
    const raw = await fs.readFile(KILL_SWITCH_PATH, "utf8");
    const data = JSON.parse(raw) as KillSwitchFile;
    return {
      enabled: Boolean(data.enabled),
      articleStopped: Boolean(data.articleEnabled),
      reason: data.reason || "",
    };
  } catch {
    return { enabled: false, articleStopped: false, reason: "" };
  }
}

export async function GET() {
  if (!(await isAuthenticated())) {
    return NextResponse.json({ error: "認証が必要です" }, { status: 401 });
  }

  const [gearmanReady, killSwitch] = await Promise.all([
    getGearmanReadyCount(),
    getKillSwitch(),
  ]);

  return NextResponse.json({
    gearman: { ready: gearmanReady },
    killSwitch,
  });
}
