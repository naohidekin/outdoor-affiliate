import { NextResponse } from "next/server";
import type { NextRequest } from "next/server";

// /admin/*（loginを除く）のサーバー側認証ガード。
// 従来は管理画面レイアウトがClient Componentで、未認証でも画面の外枠と
// 内部機能名が描画されていた（APIで401になるだけ）。ここで描画前に弾く。
// 検証ロジックは src/lib/auth.ts と同一仕様（HMAC-SHA256署名+発行時刻）だが、
// ProxyはEdge相当の実行環境のためWeb Cryptoで実装している

const SESSION_TOKEN = "outdoor-admin-session";
const MAX_AGE_MS = 7 * 24 * 60 * 60 * 1000; // Cookie maxAge(7日)とそろえる

async function verifyToken(token: string, secret: string): Promise<boolean> {
  const lastDot = token.lastIndexOf(".");
  if (lastDot === -1) return false;
  const payload = token.slice(0, lastDot);
  const signature = token.slice(lastDot + 1);

  // payload形式: authenticated:<発行時刻ms>:<nonce>
  // Cookieの7日失効はクライアント任せなので、盗まれたトークンを別経路で
  // 再設定された場合に備え、サーバー側でも発行時刻から有効期限を検証する
  const parts = payload.split(":");
  if (parts[0] !== "authenticated") return false;
  const issuedAt = Number(parts[1]);
  if (!Number.isFinite(issuedAt)) return false;
  const age = Date.now() - issuedAt;
  if (age < 0 || age > MAX_AGE_MS) return false;

  const enc = new TextEncoder();
  const key = await crypto.subtle.importKey(
    "raw",
    enc.encode(secret),
    { name: "HMAC", hash: "SHA-256" },
    false,
    ["sign"]
  );
  const mac = await crypto.subtle.sign("HMAC", key, enc.encode(payload));
  const expected = Array.from(new Uint8Array(mac))
    .map((b) => b.toString(16).padStart(2, "0"))
    .join("");
  if (expected.length !== signature.length) return false;
  let diff = 0;
  for (let i = 0; i < expected.length; i++) {
    diff |= expected.charCodeAt(i) ^ signature.charCodeAt(i);
  }
  return diff === 0;
}

export async function proxy(request: NextRequest) {
  const { pathname } = request.nextUrl;
  // ログイン画面だけは未認証で通す（ここも弾くとリダイレクトループになる）
  if (pathname === "/admin/login") return NextResponse.next();

  // 秘密鍵の解決は auth.ts と同一。本番で未設定なら fail closed
  const hasConfiguredSecret = Boolean(
    process.env.ADMIN_SESSION_SECRET || process.env.ADMIN_PASSWORD
  );
  const secret =
    process.env.ADMIN_SESSION_SECRET ||
    process.env.ADMIN_PASSWORD ||
    "fallback-secret-change-me";

  const token = request.cookies.get(SESSION_TOKEN)?.value || "";
  const authenticated =
    (hasConfiguredSecret || process.env.NODE_ENV !== "production") &&
    token !== "" &&
    (await verifyToken(token, secret));

  if (!authenticated) {
    const url = request.nextUrl.clone();
    url.pathname = "/admin/login";
    url.search = "";
    return NextResponse.redirect(url);
  }
  return NextResponse.next();
}

export const config = {
  matcher: "/admin/:path*",
};
