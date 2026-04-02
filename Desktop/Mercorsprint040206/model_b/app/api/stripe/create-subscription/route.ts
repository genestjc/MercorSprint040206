import { NextRequest, NextResponse } from "next/server";
import { stripe, stripeConfigured, STRIPE_PRICE_ID } from "@/lib/stripe";

export async function POST(req: NextRequest) {
  if (!stripeConfigured || !stripe || !STRIPE_PRICE_ID) {
    return NextResponse.json({ demo: true });
  }

  const { walletAddress } = await req.json().catch(() => ({}));

  try {
    const customer = await stripe.customers.create({
      metadata: walletAddress ? { walletAddress } : undefined,
    });

    const subscription = await stripe.subscriptions.create({
      customer: customer.id,
      items: [{ price: STRIPE_PRICE_ID }],
      payment_behavior: "default_incomplete",
      payment_settings: {
        save_default_payment_method: "on_subscription",
      },
      metadata: walletAddress ? { walletAddress } : undefined,
      expand: ["latest_invoice.payment_intent"],
    });

    const invoice = subscription.latest_invoice;
    const pi =
      invoice && typeof invoice !== "string" ? invoice.payment_intent : null;
    const clientSecret =
      pi && typeof pi !== "string" ? pi.client_secret : null;

    if (!clientSecret) {
      return NextResponse.json(
        { error: "No client secret on subscription" },
        { status: 500 }
      );
    }

    return NextResponse.json({
      subscriptionId: subscription.id,
      clientSecret,
    });
  } catch (e) {
    const message = e instanceof Error ? e.message : "Stripe error";
    return NextResponse.json({ error: message }, { status: 500 });
  }
}
