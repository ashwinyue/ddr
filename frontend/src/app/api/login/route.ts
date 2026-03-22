import { cookies } from "next/headers";
import { type NextRequest, NextResponse } from "next/server";

import { COOKIE_NAME, createSessionToken, MAX_AGE } from "@/lib/session";

export async function POST(req: NextRequest) {
  const { username, password } = (await req.json()) as {
    username: string;
    password: string;
  };

  if (
    username !== process.env.AUTH_USERNAME ||
    password !== process.env.AUTH_PASSWORD
  ) {
    return NextResponse.json({ error: "用户名或密码错误" }, { status: 401 });
  }

  const token = await createSessionToken(username);
  const cookieStore = await cookies();
  cookieStore.set(COOKIE_NAME, token, {
    httpOnly: true,
    sameSite: "lax",
    maxAge: MAX_AGE,
    path: "/",
  });

  return NextResponse.json({ ok: true });
}
