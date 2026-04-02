import { NextRequest, NextResponse } from "next/server";
import { getStripe } from "@/lib/stripe";
import { STRIPE_PRICE_ID } from "@/lib/config";

/**
 * Creates a Stripe Customer + Subscription with `payment_behavior: default_incomplete`.
 * Returns the PaymentIntent clientSecret so the frontend can mount <PaymentElement>
 * inside our custom NYT-style modal (Apple/Google Pay render automatically).
 *
 * Demo mode: returns { demo: true } — frontend renders a fake form instead.
 */
export async function POST(req: NextRequest) {
  const stripe = getStripe();

  if (!stripe || !STRIPE_PRICE_ID) {
    return NextResponse.json({ demo: true });
  }

  const { walletAddress, email } = await req.json();

  const customer = await stripe.customers.create({
    email: email || undefined,
    metadata: { walletAddress: walletAddress || "" },
  });

  const subscription = await stripe.subscriptions.create({
    customer: customer.id,
    items: [{ price: STRIPE_PRICE_ID }],
    payment_behavior: "default_incomplete",
    payment_settings: {
      save_default_payment_method: "on_subscription",
      payment_method_types: ["card"], // Apple/Google Pay surface via card
    },
    expand: ["latest_invoice.payment_intent"],
    metadata: { walletAddress: walletAddress || "" },
  });

  const invoice = subscription.latest_invoice;
  if (!invoice || typeof invoice === "string") {
    return NextResponse.json({ error: "No invoice" }, { status: 500 });
  }
  const pi = invoice.payment_intent;
  if (!pi || typeof pi === "string") {
    return NextResponse.json({ error: "No payment intent" }, { status: 500 });
  }

  return NextResponse.json({
    clientSecret: pi.client_secret,
    subscriptionId: subscription.id,
  });
}
