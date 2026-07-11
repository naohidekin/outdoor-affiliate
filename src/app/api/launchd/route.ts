import { spawn } from "node:child_process";
import { NextRequest, NextResponse } from "next/server";
import { isAuthenticated } from "@/lib/auth";

export const runtime = "nodejs";

const LABEL_KEYWORDS = ["com.gearman", "com.clinic", "com.kodomo", "com.outdoor", "com.jsh"];

type LaunchdJob = {
  label: string;
  pid: number | null;
  lastExitStatus: number | null;
};

function runLaunchctl(args: string[]): Promise<{ stdout: string; stderr: string; code: number | null }> {
  return new Promise((resolve, reject) => {
    const child = spawn("launchctl", args);
    let stdout = "";
    let stderr = "";

    child.stdout.on("data", (chunk) => {
      stdout += chunk.toString();
    });
    child.stderr.on("data", (chunk) => {
      stderr += chunk.toString();
    });
    child.on("error", reject);
    child.on("close", (code) => {
      resolve({ stdout, stderr, code });
    });
  });
}

function parseLaunchctlList(stdout: string): LaunchdJob[] {
  return stdout
    .split("\n")
    .slice(1)
    .map((line) => line.trim())
    .filter(Boolean)
    .map((line) => {
      const parts = line.split(/\s+/);
      const label = parts.slice(2).join(" ");
      return {
        label,
        pid: parts[0] === "-" ? null : Number(parts[0]),
        lastExitStatus: parts[1] === "-" ? null : Number(parts[1]),
      };
    })
    .filter((job) => job.label && LABEL_KEYWORDS.some((keyword) => job.label.includes(keyword)));
}

export async function GET() {
  if (!(await isAuthenticated())) {
    return NextResponse.json({ error: "認証が必要です" }, { status: 401 });
  }

  try {
    const result = await runLaunchctl(["list"]);
    if (result.code !== 0) {
      throw new Error(result.stderr || "launchctl list failed");
    }

    return NextResponse.json(parseLaunchctlList(result.stdout));
  } catch (error) {
    console.error("Launchd GET error:", error);
    return NextResponse.json({ error: "launchd情報の取得に失敗しました" }, { status: 500 });
  }
}

export async function POST(req: NextRequest) {
  if (!(await isAuthenticated())) {
    return NextResponse.json({ error: "認証が必要です" }, { status: 401 });
  }

  try {
    const body = (await req.json()) as { label?: string; action?: "start" | "stop" };
    if (!body.label || !body.action || !["start", "stop"].includes(body.action)) {
      return NextResponse.json({ error: "label と action が必要です" }, { status: 400 });
    }

    const result = await runLaunchctl([body.action, body.label]);
    if (result.code !== 0) {
      throw new Error(result.stderr || `launchctl ${body.action} failed`);
    }

    return NextResponse.json({ ok: true });
  } catch (error) {
    console.error("Launchd POST error:", error);
    return NextResponse.json({ error: "launchctl操作に失敗しました" }, { status: 500 });
  }
}
