import { NextRequest, NextResponse } from "next/server";
import { execFile } from "child_process";
import path from "path";
import { isAuthenticated } from "@/lib/auth";

// 新パイプライン（scripts/generate-x-posts.js）を子プロセスで実行する。
// 以前は buildLegacyBatchPrompt ベースの旧バッチを呼んでいたが、
// doctor/AI軸・viral-scout分析・品質ゲート(7.5/カテゴリ別最低点/NGリトライ)を
// 通すため CLI と同じロジックに統一した。
// Vercel Hobby プランの上限は 300 秒。新パイプラインは軸×件数×リトライで
// 最長 3〜5 分かかる見込みなので、上限いっぱいに設定する。
export const maxDuration = 300;

export async function POST(request: NextRequest) {
  if (!(await isAuthenticated())) {
    return NextResponse.json({ error: "認証が必要です" }, { status: 401 });
  }

  const body = await request.json().catch(() => ({}));
  const autoApprove = body.autoApprove === true;
  const type: string | undefined = body.type;
  const count: number | undefined = body.count;
  const axis: string | undefined = body.axis;

  const cwd = path.resolve(process.cwd());
  const script = path.join(cwd, "scripts", "generate-x-posts.js");

  const args = ["--dns-result-order=ipv4first", script];
  if (autoApprove) args.push("--auto-approve");
  if (type) args.push(`--type=${type}`);
  if (typeof count === "number") args.push(`--count=${count}`);
  if (axis) args.push(`--axis=${axis}`);

  return new Promise<NextResponse>((resolve) => {
    execFile(
      "node",
      args,
      {
        cwd,
        env: { ...process.env },
        timeout: 290_000,
        maxBuffer: 20 * 1024 * 1024,
      },
      (error, stdout, stderr) => {
        const output = (stdout + stderr).trim();
        // タイムアウトや致命的失敗
        if (error && error.code !== 0 && !stdout) {
          console.error("[generate] execFile error:", error.message);
          resolve(
            NextResponse.json(
              { ok: false, error: error.message, output: output.slice(-3000) },
              { status: 500 }
            )
          );
          return;
        }

        // 生成件数パース: "Sheets に N件を保存しました"（最終行近辺）
        const savedMatch = output.match(/Sheets に\s*(\d+)\s*件を保存/);
        const generated = savedMatch ? parseInt(savedMatch[1], 10) : 0;

        // 品質ゲートで捨てられた件数: 「品質不足」「NGチェック失敗」「類似度」
        // のログ出現回数をカウント（同じ投稿が複数回弾かれても累計でOK）
        const qualityRetries =
          (output.match(/品質不足/g)?.length || 0) +
          (output.match(/NGチェック失敗/g)?.length || 0) +
          (output.match(/類似度.*→ 再生成/g)?.length || 0);

        // blocked: validationErrors 付き（checkXPostContent で弾かれた状態）の保存件数
        const blockedMatch = output.match(/\[([^\]]+)\]\s*\d+件.*validationErrors/g);
        const blocked = blockedMatch?.length || 0;

        resolve(
          NextResponse.json({
            ok: true,
            generated,
            blocked,
            qualityRetries,
            // 最終 3000 文字（末尾）だけ返す（進捗/エラー確認用）
            output: output.slice(-3000),
          })
        );
      }
    );
  });
}
