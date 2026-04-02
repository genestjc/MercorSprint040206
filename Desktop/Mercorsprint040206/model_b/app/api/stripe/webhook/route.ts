import { NextRequest, NextResponse } from "next/server";
import Stripe from "stripe";
import { stripe, stripeConfigured } from "@/lib/stripe";
import { mintMembership, revokeMembership } from "@/lib/mint";

export const runtime = "nodejs";

const ACTIVE: Stripe.Subscription.Status[] = ["active", "trialing"];
const LAPSED: Stripe.Subscription.Status[] = [
  "canceled",
  "unpaid",
  "incomplete_expired",
];

async function walletFromSubscription(
  s: Stripe,
  subId: string | Stripe.Subscription | null
): Promise<string | undefined> {
  if (!subId) return undefined;
  const sub =
    typeof subId === "string" ? await s.subscriptions.retrieve(subId) : subId;
  return sub.metadata?.walletAddress;
}

export async function POST(req: NextRequest) {
  if (!stripeConfigured || !stripe) {
    return NextResponse.json({ demo: true });
  }

  const secret = process.env.STRIPE_WEBHOOK_SECRET;
  const sig = req.headers.get("stripe-signature");
  const raw = await req.text();

  let event: Stripe.Event;
  if (secret && sig) {
    try {
      event = stripe.webhooks.constructEvent(raw, sig, secret);
    } catch {
      return NextResponse.json({ error: "Invalid signature" }, { status: 400 });
    }
  } else if (process.env.NODE_ENV !== "production") {
    // Local dev convenience only — never accept unsigned payloads in prod.
    event = JSON.parse(raw) as Stripe.Event;
  } else {
    return NextResponse.json({ error: "Signature required" }, { status: 400 });
  }

  try {
    switch (event.type) {
      // First successful charge AND every renewal.
      case "invoice.payment_succeeded": {
        const invoice = event.data.object as Stripe.Invoice;
        const wallet = await walletFromSubscription(
          stripe,
          invoice.subscription
        );
        // Only mint on the initial subscription invoice; renewals are no-ops.
        if (wallet && invoice.billing_reason === "subscription_create") {
          await mintMembership(wallet);
        }
        break;
      }

      // Recurring charge failed → keep pass during Stripe's retry window;
      // revocation happens when the sub transitions to unpaid/canceled.
      case "invoice.payment_failed": {
        const invoice = event.data.object as Stripe.Invoice;
        const wallet = await walletFromSubscription(
          stripe,
          invoice.subscription
        );
        console.warn(
          `[stripe] payment failed for ${wallet ?? "unknown"} (invoice ${invoice.id})`
        );
        break;
      }

      // Status changes: paused, past_due → unpaid, reactivated, etc.
      case "customer.subscription.updated": {
        const sub = event.data.object as Stripe.Subscription;
        const wallet = sub.metadata?.walletAddress;
        if (!wallet) break;
        if (ACTIVE.includes(sub.status)) {
          await mintMembership(wallet); // re-grant if they reactivated
        } else if (LAPSED.includes(sub.status)) {
          await revokeMembership(wallet);
        }
        break;
      }

      // Subscription ended (cancelled or final payment failure).
      case "customer.subscription.deleted": {
        const sub = event.data.object as Stripe.Subscription;
        const wallet = sub.metadata?.walletAddress;
        if (wallet) await revokeMembership(wallet);
        break;
      }

      // Dispute / chargeback → treat as immediate revocation.
      case "charge.dispute.created": {
        const dispute = event.data.object as Stripe.Dispute;
        const charge = await stripe.charges.retrieve(
          typeof dispute.charge === "string" ? dispute.charge : dispute.charge.id
        );
        const invoiceId = charge.invoice;
        if (invoiceId) {
          const invoice = await stripe.invoices.retrieve(
            typeof invoiceId === "string" ? invoiceId : invoiceId.id
          );
          const wallet = await walletFromSubscription(
            stripe,
            invoice.subscription
          );
          if (wallet) await revokeMembership(wallet);
        }
        break;
      }

      default:
        // Unhandled event types are acknowledged so Stripe stops retrying.
        break;
    }
  } catch (e) {
    console.error(`[stripe webhook] handler error for ${event.type}:`, e);
    return NextResponse.json({ error: "handler failed" }, { status: 500 });
  }

  return NextResponse.json({ received: true });
}
