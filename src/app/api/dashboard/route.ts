import fs from "node:fs/promises";
import path from "node:path";
import { NextRequest, NextResponse } from "next/server";
import { isAuthenticated } from "@/lib/auth";

export const runtime = "nodejs";

const HOME = process.env.HOME || "";
const GEARMAN_QUEUE_PATH = path.join(process.cwd(), "data", "post-queue.json");
const AMBLE_POSTS_PATH = path.join(HOME, "Desktop/AI関連/claude/san-pedinvestor-x/data/x-posts.json");
const KODOMO_POSTS_PATH = path.join(HOME, "Desktop/AI関連/parent-child-medical/data/x/posts.jsonl");
const KILL_SWITCH_PATH = path.join(process.cwd(), "data", "kill-switch.json");

type GearmanQueueItem = { status?: string };
type AmblePost = { status?: string };
type KodomoPost = { status?: string };
type KillSwitchState = { enabled?: boolean };

async function getGearmanReadyCount(): Promise<number> {
  try {
    const raw = await fs.readFile(GEARMAN_QUEUE_PATH, "utf8");
    const data = JSON.parse(raw) as { queue?: GearmanQueueItem[] };
    return (data.queue || []).filter((item) => item.status === "ready").length;
  } catch {
    return 0;
  }
}

async function getAmbleCounts(): Promise<{ draft: number; approved: number }> {
  try {
    const raw = await fs.readFile(AMBLE_POSTS_PATH, "utf8");
    const posts = JSON.parse(raw) as AmblePost[];
    return {
      draft: posts.filter((item) => item.status === "draft").length,
      approved: posts.filter((item) => item.status === "approved").length,
    };
  } catch {
    return { draft: 0, approved: 0 };
  }
}

async function getKodomoReviewedCount(): Promise<number> {
  try {
    const raw = await fs.readFile(KODOMO_POSTS_PATH, "utf8");
    return raw
      .split("\n")
      .filter((line) => line.trim())
      .map((line) => JSON.parse(line) as KodomoPost)
      .filter((item) => item.status === "reviewed").length;
  } catch {
    return 0;
  }
}

async function getKillSwitchEnabled(): Promise<boolean> {
  try {
    const raw = await fs.readFile(KILL_SWITCH_PATH, "utf8");
    const data = JSON.parse(raw) as KillSwitchState;
    return Boolean(data.enabled);
  } catch {
    return false;
  }
}

export async function GET(req: NextRequest) {
  if (!(await isAuthenticated())) {
    return NextResponse.json({ error: "認証が必要です" }, { status: 401 });
  }

  const [gearmanReady, ambleCounts, kodomoReviewed, killSwitchEnabled] = await Promise.all([
    getGearmanReadyCount(),
    getAmbleCounts(),
    getKodomoReviewedCount(),
    getKillSwitchEnabled(),
  ]);

  return NextResponse.json({
    gearman: { ready: gearmanReady },
    amble: ambleCounts,
    kodomo: { reviewed: kodomoReviewed },
    killSwitch: { enabled: killSwitchEnabled },
  });
}
