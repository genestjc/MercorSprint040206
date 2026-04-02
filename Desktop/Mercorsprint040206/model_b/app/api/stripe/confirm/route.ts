import { NextRequest, NextResponse } from "next/server";
import type Stripe from "stripe";
import { stripe, stripeConfigured } from "@/lib/stripe";
import { setMemberSession } from "@/lib/session";

/**
 * Stripe redirects here after confirmPayment(). We re-fetch the
 * PaymentIntent server-side, verify it actually succeeded, then issue a
 * signed member session cookie. This is the only path (besides the dev-only
 * demo route) that grants access.
 */
export async function GET(req: NextRequest) {
  const url = new URL(req.url);
  const piId = url.searchParams.get("payment_intent");
  const dest = new URL("/videos", url.origin);

  if (!stripeConfigured || !stripe || !piId) {
    dest.searchParams.set("error", "payment_not_verified");
    return NextResponse.redirect(dest);
  }

  const pi = await stripe.paymentIntents.retrieve(piId, {
    expand: ["invoice.subscription"],
  });

  if (pi.status !== "succeeded") {
    dest.searchParams.set("error", pi.status);
    return NextResponse.redirect(dest);
  }

  let subscriptionId: string | undefined;
  let wallet: string | undefined;
  const invoice = pi.invoice;
  if (invoice && typeof invoice !== "string") {
    const sub = invoice.subscription;
    if (sub && typeof sub !== "string") {
      subscriptionId = sub.id;
      wallet = (sub as Stripe.Subscription).metadata?.walletAddress;
    } else if (typeof sub === "string") {
      subscriptionId = sub;
    }
  }

  await setMemberSession({ wallet, subscriptionId });
  dest.searchParams.set("subscribed", "1");
  return NextResponse.redirect(dest);
}
