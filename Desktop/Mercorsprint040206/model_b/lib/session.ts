import { SignJWT, jwtVerify } from "jose";
import { cookies } from "next/headers";

const COOKIE = "member_session";

function key() {
  const secret =
    process.env.SESSION_SECRET || "dev-only-insecure-secret-change-me";
  return new TextEncoder().encode(secret);
}

export type MemberSession = {
  wallet?: string;
  subscriptionId?: string;
  demo?: boolean;
};

export async function setMemberSession(payload: MemberSession) {
  const token = await new SignJWT(payload as Record<string, unknown>)
    .setProtectedHeader({ alg: "HS256" })
    .setIssuedAt()
    .setExpirationTime("30d")
    .sign(key());

  cookies().set(COOKIE, token, {
    httpOnly: true,
    sameSite: "lax",
    secure: process.env.NODE_ENV === "production",
    path: "/",
    maxAge: 60 * 60 * 24 * 30,
  });
}

export async function getMemberSession(): Promise<MemberSession | null> {
  const token = cookies().get(COOKIE)?.value;
  if (!token) return null;
  try {
    const { payload } = await jwtVerify(token, key());
    return payload as MemberSession;
  } catch {
    return null;
  }
}

export function clearMemberSession() {
  cookies().delete(COOKIE);
}
