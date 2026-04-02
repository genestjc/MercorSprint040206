import { timingSafeEqual } from "crypto";

/**
 * Returns true if the request carries a valid x-admin-secret header.
 * If ADMIN_SECRET is unset (demo), all requests are allowed.
 */
export function isAdmin(req: Request): boolean {
  const secret = process.env.ADMIN_SECRET;
  if (!secret) return true;

  const provided = req.headers.get("x-admin-secret") ?? "";
  const a = Buffer.from(secret);
  const b = Buffer.from(provided);
  return a.length === b.length && timingSafeEqual(a, b);
}
