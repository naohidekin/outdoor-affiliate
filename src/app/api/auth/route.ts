import { ANALYTICS_EXCLUSION_COOKIE, ANALYTICS_EXCLUSION_MAX_AGE } from "@/lib/analyticsExclusion";
import { NextRequest, NextResponse } from "next/server";
import { verifyPassword, createSessionToken, SESSION_TOKEN } from "@/lib/auth";

export async function POST(request: NextRequest) {
  const { password } = await request.json();

  if (!verifyPassword(password)) {
    return NextResponse.json({ error: "パスワードが正しくありません" }, { status: 401 });
  }

  const response = NextResponse.json({ success: true });
  response.cookies.set(SESSION_TOKEN, createSessionToken(), {
    httpOnly: true,
    secure: process.env.NODE_ENV === "production",
    sameSite: "lax",
    maxAge: 60 * 60 * 24 * 7, // 7 days
    path: "/",
  });

  response.cookies.set(ANALYTICS_EXCLUSION_COOKIE, "1", { path: "/", sameSite: "lax", secure: process.env.NODE_ENV === "production", maxAge: ANALYTICS_EXCLUSION_MAX_AGE });
  return response;
}

export async function DELETE() {
  const response = NextResponse.json({ success: true });
  response.cookies.delete(SESSION_TOKEN);
  return response;
}
