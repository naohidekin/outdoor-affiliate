import { NextResponse } from "next/server";
import { isAuthenticated } from "@/lib/auth";
import { execFile } from "child_process";
import path from "path";

export async function POST() {
  if (!(await isAuthenticated())) {
    return NextResponse.json({ error: "認証が必要です" }, { status: 401 });
  }

  const cwd = path.resolve(process.cwd());
  const script = path.join(cwd, "scripts", "post-to-x.js");

  return new Promise<NextResponse>((resolve) => {
    execFile(
      "node",
      [script, "--max=1"],
      { cwd, env: { ...process.env }, timeout: 60_000 },
      (error, stdout, stderr) => {
        const output = (stdout + stderr).trim();
        if (error && error.code !== 0) {
          resolve(NextResponse.json({ ok: false, output }, { status: 500 }));
        } else {
          resolve(NextResponse.json({ ok: true, output }));
        }
      }
    );
  });
}
