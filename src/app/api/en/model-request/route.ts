import { NextResponse } from "next/server";

/**
 * 未登録型番リクエストの中継
 *
 * ブラウザからは送信先URLを見せず、ここで `MODEL_REQUEST_FORM_URL` へ渡す。
 * 新しいDBやサービスは導入しない。中身を保存するのは設定された外部先の役目。
 *
 * 未設定なら 503 を返し、クライアントはそもそもフォームを描かない
 * （二重の防御。環境変数が消えた状態で入力させて捨てる事故を防ぐ）。
 *
 * ここに来る内容は自由入力とメールアドレスを含む。
 * **ログにも analytics にも出さない。** 外へ渡すだけにする。
 */

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

const MAX_BODY_BYTES = 8 * 1024;

const LIMITS: Record<string, number> = {
  modelNumber: 80,
  productName: 160,
  market: 16,
  purpose: 1000,
  email: 200,
};

const ALLOWED_MARKETS = new Set(["", "us", "jp", "other"]);

function clean(value: unknown, max: number): string {
  if (typeof value !== "string") return "";
  return value.trim().slice(0, max);
}

export async function POST(request: Request) {
  const endpoint = process.env.MODEL_REQUEST_FORM_URL;
  if (!endpoint) {
    return NextResponse.json(
      { error: "Model requests are not configured on this deployment." },
      { status: 503 }
    );
  }

  const raw = await request.text();
  if (raw.length > MAX_BODY_BYTES) {
    return NextResponse.json({ error: "Request too large." }, { status: 413 });
  }

  let parsed: unknown;
  try {
    parsed = JSON.parse(raw);
  } catch {
    return NextResponse.json({ error: "Invalid JSON." }, { status: 400 });
  }
  if (typeof parsed !== "object" || parsed === null) {
    return NextResponse.json({ error: "Invalid payload." }, { status: 400 });
  }

  const body = parsed as Record<string, unknown>;
  const modelNumber = clean(body.modelNumber, LIMITS.modelNumber);
  if (modelNumber === "") {
    return NextResponse.json({ error: "Model number is required." }, { status: 400 });
  }

  const market = clean(body.market, LIMITS.market);
  const payload = {
    modelNumber,
    productName: clean(body.productName, LIMITS.productName),
    market: ALLOWED_MARKETS.has(market) ? market : "other",
    purpose: clean(body.purpose, LIMITS.purpose),
    email: clean(body.email, LIMITS.email),
    submittedAt: new Date().toISOString(),
    source: "en/snow-peak-igt-model-finder",
  };

  try {
    const res = await fetch(endpoint, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
      signal: AbortSignal.timeout(10_000),
    });
    if (!res.ok) {
      // 送信先のステータスだけ残す。本文は入力内容を含みうるのでログに出さない
      console.error(`[en/model-request] upstream responded ${res.status}`);
      return NextResponse.json({ error: "Upstream rejected the request." }, { status: 502 });
    }
  } catch (e) {
    console.error(
      `[en/model-request] upstream failed: ${e instanceof Error ? e.name : "unknown"}`
    );
    return NextResponse.json({ error: "Could not reach the form endpoint." }, { status: 502 });
  }

  return NextResponse.json({ ok: true });
}
