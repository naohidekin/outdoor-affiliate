import { cookies } from "next/headers";
import crypto from "crypto";

const ADMIN_PASSWORD = process.env.ADMIN_PASSWORD || "admin123";
const SESSION_TOKEN = "outdoor-admin-session";
const HMAC_SECRET = process.env.ADMIN_SESSION_SECRET || process.env.ADMIN_PASSWORD || "fallback-secret-change-me";

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
  return crypto.timingSafeEqual(Buffer.from(signature), Buffer.from(expected));
}

export function createSessionToken(): string {
  const payload = `authenticated:${Date.now()}:${crypto.randomBytes(16).toString("hex")}`;
  return signToken(payload);
}

export async function isAuthenticated(): Promise<boolean> {
  const cookieStore = await cookies();
  const value = cookieStore.get(SESSION_TOKEN)?.value;
  if (!value) return false;
  // 後方互換: 旧トークン "authenticated" も一時的に許可（次回ログインで置き換え）
  if (value === "authenticated") return true;
  return verifyToken(value);
}

export function verifyPassword(password: string): boolean {
  return password === ADMIN_PASSWORD;
}

export { SESSION_TOKEN };
