import { type NextRequest, NextResponse } from "next/server";

const COOKIE_NAME = "auth_session";
const PUBLIC_PATHS = ["/login", "/api/login"];

async function verifyToken(token: string): Promise<boolean> {
  const secret = process.env.AUTH_SECRET ?? "";
  const lastDot = token.lastIndexOf(".");
  if (lastDot === -1) return false;

  const payload = token.slice(0, lastDot);
  const sigHex = token.slice(lastDot + 1);

  const encoder = new TextEncoder();
  const key = await crypto.subtle.importKey(
    "raw",
    encoder.encode(secret),
    { name: "HMAC", hash: "SHA-256" },
    false,
    ["verify"],
  );

  const sigBytes = new Uint8Array(
    (sigHex.match(/.{2}/g) ?? []).map((b) => parseInt(b, 16)),
  );

  return crypto.subtle.verify("HMAC", key, sigBytes, encoder.encode(payload));
}

export async function proxy(req: NextRequest) {
  const { pathname } = req.nextUrl;

  if (PUBLIC_PATHS.some((p) => pathname.startsWith(p))) {
    return NextResponse.next();
  }

  const token = req.cookies.get(COOKIE_NAME)?.value;
  if (!token || !(await verifyToken(token))) {
    const loginUrl = new URL("/login", req.url);
    loginUrl.searchParams.set("from", pathname);
    return NextResponse.redirect(loginUrl);
  }

  return NextResponse.next();
}

export const config = {
  matcher: ["/((?!_next/static|_next/image|favicon.ico).*)"],
};
