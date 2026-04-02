import { NextRequest, NextResponse } from "next/server";
import Stripe from "stripe";
import { getStripe } from "@/lib/stripe";

/**
 * Stripe webhook → on-chain membership state machine.
 *
 * The NFT is the single source of truth for access. This handler keeps it
 * in sync with Stripe's subscription status:
 *
 *   invoice.paid                      → MINT   (first sub OR card fixed after decline)
 *   invoice.payment_failed            → log    (no action — Stripe retries; status flip handles it)
 *   customer.subscription.updated     → REVOKE if status ∈ {past_due, unpaid, canceled, incomplete_expired}
 *                                       MINT   if status flipped back to active|trialing
 *   customer.subscription.deleted     → REVOKE (final — cancel-now or retries exhausted)
 *
 * Both mint and revoke are idempotent: the contract's `memberToken` mapping
 * means double-mint reverts and double-revoke reverts. We swallow those
 * reverts here so Stripe doesn't keep retrying the webhook.
 *
 * Configure these four events in your Stripe dashboard webhook endpoint.
 */

// Subscription statuses that should NOT have access.
const REVOKED_STATUSES: ReadonlySet<Stripe.Subscription.Status> = new Set([
  "past_due",
  "unpaid",
  "canceled",
  "incomplete_expired",
]);

// Statuses that SHOULD have access.
const ACTIVE_STATUSES: ReadonlySet<Stripe.Subscription.Status> = new Set([
  "active",
  "trialing",
]);

export async function POST(req: NextRequest) {
  const stripe = getStripe();
  const secret = process.env.STRIPE_WEBHOOK_SECRET;

  if (!stripe || !secret) {
    return NextResponse.json({ received: true, demo: true });
  }

  const body = await req.text();
  const sig = req.headers.get("stripe-signature");
  if (!sig) {
    return NextResponse.json({ error: "No signature" }, { status: 400 });
  }

  let event: Stripe.Event;
  try {
    event = stripe.webhooks.constructEvent(body, sig, secret);
  } catch (err) {
    const msg = err instanceof Error ? err.message : "Invalid signature";
    return NextResponse.json({ error: msg }, { status: 400 });
  }

  switch (event.type) {
    // ────────────────────────────────────────────────────────────────────────
    // Payment succeeded — covers BOTH first subscription and recovery after
    // a declined renewal. Always mint; if already a member, it's a no-op.
    // ────────────────────────────────────────────────────────────────────────
    case "invoice.paid": {
      const invoice = event.data.object;
      const wallet = await resolveWallet(stripe, invoice.subscription);
      if (wallet) {
        await mintPass(wallet, `invoice.paid (${invoice.billing_reason})`);
      }
      break;
    }

    // ────────────────────────────────────────────────────────────────────────
    // Renewal charge declined. We DON'T revoke here — Stripe's smart retry
    // schedule runs (~3 attempts over ~2 weeks). The subscription status
    // flips to past_due immediately, which the .updated handler below catches.
    // Keeping this case so the event is acknowledged and you have a log hook.
    // ────────────────────────────────────────────────────────────────────────
    case "invoice.payment_failed": {
      const invoice = event.data.object;
      const wallet = await resolveWallet(stripe, invoice.subscription);
      console.warn(
        `[webhook] payment failed for ${wallet ?? "unknown"} — ` +
          `attempt ${invoice.attempt_count}, next retry ${
            invoice.next_payment_attempt
              ? new Date(invoice.next_payment_attempt * 1000).toISOString()
              : "none"
          }`
      );
      break;
    }

    // ────────────────────────────────────────────────────────────────────────
    // Status transitions. This is where revoke-on-decline actually happens:
    // when a renewal fails, status goes active → past_due → (retries) →
    // unpaid or canceled. We revoke as soon as it leaves active.
    //
    // If the user updates their card and the retry succeeds, status flips
    // back to active AND invoice.paid fires — both paths re-mint.
    //
    // cancel_at_period_end=true keeps status=active until the period ends,
    // so users keep access through the time they've paid for. Correct.
    // ────────────────────────────────────────────────────────────────────────
    case "customer.subscription.updated": {
      const sub = event.data.object;
      const prev = event.data.previous_attributes as
        | Partial<Stripe.Subscription>
        | undefined;
      const wallet = sub.metadata.walletAddress;
      if (!wallet) break;

      // Only act on actual status transitions, not unrelated updates
      // (e.g., metadata changes, plan swaps).
      const statusChanged = prev && "status" in prev;
      if (!statusChanged) break;

      if (REVOKED_STATUSES.has(sub.status)) {
        await revokePass(
          wallet,
          `subscription.updated → ${sub.status} (was ${prev.status})`
        );
      } else if (ACTIVE_STATUSES.has(sub.status)) {
        await mintPass(
          wallet,
          `subscription.updated → ${sub.status} (was ${prev.status})`
        );
      }
      break;
    }

    // ────────────────────────────────────────────────────────────────────────
    // Terminal: subscription deleted. Fires on cancel-immediately, OR when
    // retries are exhausted, OR at period end after cancel_at_period_end.
    // ────────────────────────────────────────────────────────────────────────
    case "customer.subscription.deleted": {
      const sub = event.data.object;
      const wallet = sub.metadata.walletAddress;
      if (wallet) {
        await revokePass(wallet, "subscription.deleted");
      }
      break;
    }
  }

  return NextResponse.json({ received: true });
}

// ──────────────────────────────────────────────────────────────────────────────

async function resolveWallet(
  stripe: Stripe,
  subscription: string | Stripe.Subscription | null
): Promise<string | null> {
  if (!subscription) return null;
  if (typeof subscription === "string") {
    const sub = await stripe.subscriptions.retrieve(subscription);
    return sub.metadata.walletAddress || null;
  }
  return subscription.metadata.walletAddress || null;
}

/**
 * Mint a MembershipPass NFT. Swallows "already a member" reverts so the
 * webhook stays idempotent — Stripe will retry on 5xx, and we don't want
 * a renewal invoice.paid to loop forever just because the NFT already exists.
 */
async function mintPass(wallet: string, reason: string): Promise<void> {
  console.log(`[webhook] MINT → ${wallet}  (${reason})`);
  // TODO: ThirdWeb backend wallet → MembershipPass.mint(wallet)
  //   import { getContract, prepareContractCall, sendTransaction } from "thirdweb";
  //   const tx = prepareContractCall({ contract, method: "mint", params: [wallet] });
  //   try { await sendTransaction({ transaction: tx, account: backendAccount }); }
  //   catch (e) { if (!String(e).includes("already a member")) throw e; }
}

/**
 * Burn a MembershipPass NFT. Swallows "not a member" reverts (e.g., webhook
 * delivered twice, or .updated and .deleted both fire for the same cancel).
 */
async function revokePass(wallet: string, reason: string): Promise<void> {
  console.log(`[webhook] REVOKE → ${wallet}  (${reason})`);
  // TODO: ThirdWeb backend wallet → MembershipPass.revoke(wallet)
  //   try { await sendTransaction({ ... method: "revoke", params: [wallet] }); }
  //   catch (e) { if (!String(e).includes("not a member")) throw e; }
}
