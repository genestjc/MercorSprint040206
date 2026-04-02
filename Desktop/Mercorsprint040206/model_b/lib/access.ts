import { getMemberSession } from "./session";

/**
 * Server-side membership check.
 * Verifies a signed JWT cookie that is only ever set after the server has
 * confirmed a successful Stripe PaymentIntent (or via the demo simulate
 * route). The cookie cannot be forged without SESSION_SECRET.
 */
export async function hasAccess(): Promise<boolean> {
  const session = await getMemberSession();
  return !!session;
}
