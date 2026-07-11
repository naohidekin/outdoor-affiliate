import { cookies } from "next/headers";
import crypto from "crypto";

// 本番では ADMIN_PASSWORD 必須（未設定なら fail closed = ログイン不可）。
// 開発環境のみ、未設定時に旧デフォルト "admin123" を警告付きで許可する。
const ADMIN_PASSWORD = process.env.ADMIN_PASSWORD || "";
const SESSION_TOKEN = "outdoor-admin-session";
const HMAC_SECRET = process.env.ADMIN_SESSION_SECRET || process.env.ADMIN_PASSWORD || "fallback-secret-change-me";
// 秘密鍵が実質未設定（=リポジトリ公開のフォールバック定数）の本番では、
// Cookieが偽造可能になるため isAuthenticated 自体を fail closed にする
const HAS_CONFIGURED_SECRET = Boolean(process.env.ADMIN_SESSION_SECRET || process.env.ADMIN_PASSWORD);

function signToken(payload: string): string {
  const hmac = crypto.createHmac("sha256", HMAC_SECRET);
  hmac.update(payload);
  return `${payload}.${hmac.digest("hex")}`;
}

function verifyToken(token: string): boolean {
  const lastDot = token.lastIndexOf(".");
  if (lastDot === -1) return false;
  const payload = token.slice(0, lastDot);
  const signature = token.slice(lastDot + 1);
  const hmac = crypto.createHmac("sha256", HMAC_SECRET);
  hmac.update(payload);
  const expected = hmac.digest("hex");
  // timingSafeEqual は長さ不一致で throw するため、事前に長さを確認する
  if (signature.length !== expected.length) return false;
  try {
    return crypto.timingSafeEqual(Buffer.from(signature), Buffer.from(expected));
  } catch {
    return false;
  }
}

export function createSessionToken(): string {
  const payload = `authenticated:${Date.now()}:${crypto.randomBytes(16).toString("hex")}`;
  return signToken(payload);
}

export async function isAuthenticated(): Promise<boolean> {
  if (!HAS_CONFIGURED_SECRET && process.env.NODE_ENV === "production") return false;
  const cookieStore = await cookies();
  const value = cookieStore.get(SESSION_TOKEN)?.value;
  if (!value) return false;
  // 旧平文トークン "authenticated" の受理は廃止（署名なしCookie 1個で全APIが開く穴だったため）
  return verifyToken(value);
}

export function verifyPassword(password: string): boolean {
  if (!ADMIN_PASSWORD) {
    if (process.env.NODE_ENV !== "production") {
      console.warn("[auth] ADMIN_PASSWORD 未設定。開発用デフォルトを一時許可しています（本番では必ず設定を）");
      return password === "admin123";
    }
    return false; // 本番は fail closed
  }
  return password === ADMIN_PASSWORD;
}

export { SESSION_TOKEN };
