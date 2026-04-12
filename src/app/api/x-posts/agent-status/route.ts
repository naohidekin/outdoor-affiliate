import { NextResponse } from "next/server";
import { isAuthenticated } from "@/lib/auth";
import fs from "fs";
import path from "path";

const DATA_DIR = path.join(process.cwd(), "data");
const LOG_DIR = path.join(process.cwd(), "logs");

function readDataJson(filename: string) {
  try {
    const raw = fs.readFileSync(path.join(DATA_DIR, filename), "utf-8");
    return JSON.parse(raw);
  } catch {
    return null;
  }
}

function readRecentErrors(maxLines = 10): Array<{ timestamp: string; label: string; exitCode: number }> {
  try {
    const raw = fs.readFileSync(path.join(LOG_DIR, "error-history.jsonl"), "utf-8");
    const lines = raw.trim().split("\n").filter(Boolean);
    return lines.slice(-maxLines).map((line) => JSON.parse(line)).reverse();
  } catch {
    return [];
  }
}

export async function GET() {
  if (!(await isAuthenticated())) {
    return NextResponse.json({ error: "認証が必要です" }, { status: 401 });
  }

  const killSwitch = readDataJson("kill-switch.json") || {
    enabled: false,
    reason: "",
    enabledAt: null,
  };

  const weeklyReport = readDataJson("weekly-report.json");

  const feedback = readDataJson("analyst-feedback.json");

  const postHistory = readDataJson("post-history.json");
  const entryCount = postHistory?.entries?.length ?? 0;

  return NextResponse.json({
    killSwitch: {
      enabled: killSwitch.enabled,
      reason: killSwitch.reason,
      enabledAt: killSwitch.enabledAt,
    },
    lastWeeklyReport: weeklyReport
      ? {
          week: weeklyReport.week,
          generatedAt: weeklyReport.generatedAt,
          summary: weeklyReport.summary,
          warnings: weeklyReport.warnings,
        }
      : null,
    analystFeedback: feedback?.updatedAt
      ? {
          updatedAt: feedback.updatedAt,
          topPerformingTypes: feedback.topPerformingTypes,
          writerHints: feedback.writerHints,
        }
      : null,
    postHistoryCount: entryCount,
    recentErrors: readRecentErrors(),
  });
}
