const COOKIE_NAME = "auth_session";
const MAX_AGE = 60 * 60 * 24 * 7; // 7 天

async function hmacHex(payload: string): Promise<string> {
  const secret = process.env.AUTH_SECRET ?? "";
  const encoder = new TextEncoder();
  const key = await crypto.subtle.importKey(
    "raw",
    encoder.encode(secret),
    { name: "HMAC", hash: "SHA-256" },
    false,
    ["sign"],
  );
  const sig = await crypto.subtle.sign("HMAC", key, encoder.encode(payload));
  return Array.from(new Uint8Array(sig))
    .map((b) => b.toString(16).padStart(2, "0"))
    .join("");
}

export async function createSessionToken(username: string): Promise<string> {
  const payload = `${username}:${Date.now()}`;
  const sig = await hmacHex(payload);
  return `${payload}.${sig}`;
}

export { COOKIE_NAME, MAX_AGE };
