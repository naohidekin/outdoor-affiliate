import { NextRequest, NextResponse } from "next/server";
import { spawn } from "child_process";
import path from "path";
import { isAuthenticated } from "@/lib/auth";

export const dynamic = "force-dynamic";
export const maxDuration = 120;

export async function POST(req: NextRequest) {
  if (!(await isAuthenticated())) {
    return NextResponse.json({ error: "認証が必要です" }, { status: 401 });
  }

  const { theme, style } = await req.json();
  if (!theme || !style) {
    return NextResponse.json({ error: "theme と style は必須です" }, { status: 400 });
  }

  const projectRoot = process.cwd();
  const scriptPath = path.join(projectRoot, "scripts", "generate-4koma.mjs");

  const stream = new ReadableStream({
    start(controller) {
      const enc = new TextEncoder();
      const send = (data: Record<string, unknown>) => {
        controller.enqueue(enc.encode(`data: ${JSON.stringify(data)}\n\n`));
      };

      const proc = spawn("node", [scriptPath, `--theme=${theme}`, `--style=${style}`], {
        cwd: projectRoot,
        env: { ...process.env },
      });

      let outputPath: string | null = null;

      proc.stdout.on("data", (chunk: Buffer) => {
        const text = chunk.toString();
        const match = text.match(/public\/images\/4koma\/[^\s]+\.png/);
        if (match) outputPath = "/" + match[0];
        send({ log: text });
      });

      proc.stderr.on("data", (chunk: Buffer) => {
        send({ log: chunk.toString() });
      });

      proc.on("close", (code) => {
        send({ done: true, code, imagePath: outputPath });
        controller.close();
      });

      proc.on("error", (err) => {
        send({ log: `[ERROR] ${err.message}`, done: true, code: 1, imagePath: null });
        controller.close();
      });
    },
  });

  return new Response(stream, {
    headers: {
      "Content-Type": "text/event-stream",
      "Cache-Control": "no-cache",
      Connection: "keep-alive",
    },
  });
}
