"use client";

import { useEffect, useState } from "react";
import { loadStripe } from "@stripe/stripe-js";
import {
  Elements,
  PaymentElement,
  useStripe,
  useElements,
} from "@stripe/react-stripe-js";
import { useActiveAccount, useConnectModal } from "thirdweb/react";
import { inAppWallet, createWallet } from "thirdweb/wallets";
import { thirdwebClient, chain } from "@/lib/thirdweb";
import { clientDemo } from "@/lib/config";
import { useMembership } from "./MembershipContext";

const paywallWallets = [
  inAppWallet({
    auth: { options: ["google", "apple", "email", "passkey"] },
  }),
  createWallet("io.metamask"),
  createWallet("com.coinbase.wallet"),
];

/**
 * NYT/WSJ-style paywall overlay.
 *
 * - Full-screen dark backdrop with blur
 * - White card slides up from bottom
 * - Helvetica headline / Arial body (brand fonts)
 * - Stripe Payment Element with Apple/Google Pay first
 * - Sign-in gate before payment (ThirdWeb embedded wallet or demo)
 *
 * Demo mode (no Stripe keys): identical UI, fake card form, 800ms "processing".
 */

const stripePromise = process.env.NEXT_PUBLIC_STRIPE_PUBLISHABLE_KEY
  ? loadStripe(process.env.NEXT_PUBLIC_STRIPE_PUBLISHABLE_KEY)
  : null;

const PRICE_DISPLAY = "$9.99";
const INTERVAL_DISPLAY = "month";

interface Props {
  open: boolean;
  onClose: () => void;
}

export function PaywallModal({ open, onClose }: Props) {
  const [mounted, setMounted] = useState(false);
  useEffect(() => {
    if (open) requestAnimationFrame(() => setMounted(true));
    else setMounted(false);
  }, [open]);

  if (!open) return null;

  return (
    <div
      className="fixed inset-0 z-50 flex items-end sm:items-center justify-center bg-black/70 backdrop-blur-sm"
      onClick={onClose}
    >
      <div
        className={`w-full sm:max-w-md bg-white sm:rounded-2xl shadow-2xl
                    max-h-[90vh] overflow-y-auto
                    transition-transform duration-300 ease-out
                    ${mounted ? "translate-y-0" : "translate-y-full sm:translate-y-8"}`}
        onClick={(e) => e.stopPropagation()}
      >
        <button
          onClick={onClose}
          className="absolute top-4 right-4 text-zinc-400 hover:text-zinc-600 text-2xl leading-none"
          aria-label="Close"
        >
          ×
        </button>

        <div className="px-8 pt-10 pb-6 text-center">
          <h2 className="font-title font-bold text-2xl text-zinc-900 leading-tight mb-3">
            Unlock unlimited video access
          </h2>
          <p className="font-body text-zinc-600 text-sm">
            Join today for full access to every video in our library.
          </p>

          <div className="mt-6 inline-flex items-baseline gap-1">
            <span className="font-title font-bold text-4xl text-zinc-900">
              {PRICE_DISPLAY}
            </span>
            <span className="font-body text-zinc-500 text-sm">
              / {INTERVAL_DISPLAY}
            </span>
          </div>
          <p className="font-body text-xs text-zinc-400 mt-1">
            Cancel anytime
          </p>
        </div>

        <div className="px-8 pb-8">
          <PaywallContent onSuccess={onClose} />
        </div>
      </div>
    </div>
  );
}

// ─────────────────────────────────────────────────────────────────────────────

function PaywallContent({ onSuccess }: { onSuccess: () => void }) {
  const account = useActiveAccount();
  const { connect, isConnecting } = useConnectModal();
  const { isSignedIn, walletAddress, signInDemo, grantMembership } =
    useMembership();

  const signedIn = !!account || isSignedIn;

  const handleSignIn = async () => {
    if (clientDemo.thirdweb || !thirdwebClient) {
      signInDemo();
      return;
    }
    // Open the real ThirdWeb embedded-wallet modal (Google/Apple/Email/passkey).
    // Resolves once a wallet is connected; the active account hook then updates
    // and this component re-renders past the gate into the payment step.
    try {
      await connect({
        client: thirdwebClient,
        wallets: paywallWallets,
        chain,
        theme: "light",
        size: "compact",
        title: "Sign in to subscribe",
      });
    } catch {
      // user closed the modal — no-op
    }
  };

  // ── Sign-in gate ──────────────────────────────────────────────────────────
  if (!signedIn) {
    return (
      <div className="text-center">
        <p className="font-body text-sm text-zinc-600 mb-4">
          Sign in with Google, Apple, or email to continue.
        </p>
        <button
          onClick={handleSignIn}
          disabled={isConnecting}
          className="w-full font-title font-bold py-3 rounded-lg bg-black text-white hover:bg-zinc-800 disabled:opacity-50 transition"
        >
          {isConnecting ? "Connecting…" : "Sign in to subscribe"}
        </button>
        <p className="font-body text-xs text-zinc-400 mt-3">
          {clientDemo.thirdweb
            ? "Demo mode — creates a local test wallet"
            : "Powered by ThirdWeb embedded wallet"}
        </p>
      </div>
    );
  }

  // ── Demo Stripe ───────────────────────────────────────────────────────────
  if (clientDemo.stripe || !stripePromise) {
    return (
      <DemoCheckout
        onSuccess={() => {
          grantMembership();
          onSuccess();
        }}
      />
    );
  }

  // ── Real Stripe ───────────────────────────────────────────────────────────
  return (
    <RealCheckout
      walletAddress={walletAddress!}
      onSuccess={() => {
        grantMembership();
        onSuccess();
      }}
    />
  );
}

// ─────────────────────────────────────────────────────────────────────────────
// Demo checkout — fake card form, identical visual layout to real Payment Element

function DemoCheckout({ onSuccess }: { onSuccess: () => void }) {
  const [processing, setProcessing] = useState(false);

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setProcessing(true);
    await new Promise((r) => setTimeout(r, 800));
    onSuccess();
  };

  return (
    <form onSubmit={submit} className="space-y-4">
      <div className="grid grid-cols-2 gap-2">
        <button
          type="button"
          className="font-body text-sm py-3 rounded-lg bg-black text-white flex items-center justify-center gap-2"
        >
           Pay
        </button>
        <button
          type="button"
          className="font-body text-sm py-3 rounded-lg bg-white border border-zinc-300 flex items-center justify-center gap-2"
        >
          G Pay
        </button>
      </div>

      <div className="relative">
        <div className="absolute inset-0 flex items-center">
          <div className="w-full border-t border-zinc-200" />
        </div>
        <div className="relative flex justify-center">
          <span className="font-body text-xs text-zinc-400 bg-white px-3">
            or pay with card
          </span>
        </div>
      </div>

      <div className="space-y-3">
        <input
          placeholder="1234 1234 1234 1234"
          className="w-full font-body text-sm px-4 py-3 border border-zinc-300 rounded-lg focus:border-black focus:outline-none"
        />
        <div className="grid grid-cols-2 gap-3">
          <input
            placeholder="MM / YY"
            className="font-body text-sm px-4 py-3 border border-zinc-300 rounded-lg focus:border-black focus:outline-none"
          />
          <input
            placeholder="CVC"
            className="font-body text-sm px-4 py-3 border border-zinc-300 rounded-lg focus:border-black focus:outline-none"
          />
        </div>
      </div>

      <button
        type="submit"
        disabled={processing}
        className="w-full font-title font-bold py-3 rounded-lg bg-black text-white hover:bg-zinc-800 disabled:opacity-50 transition"
      >
        {processing ? "Processing…" : `Subscribe for ${PRICE_DISPLAY}/${INTERVAL_DISPLAY}`}
      </button>

      <p className="font-body text-[10px] text-center text-zinc-400">
        Demo mode — no real charge will be made
      </p>
    </form>
  );
}

// ─────────────────────────────────────────────────────────────────────────────
// Real checkout — Stripe Payment Element wrapped in <Elements>

function RealCheckout({
  walletAddress,
  onSuccess,
}: {
  walletAddress: string;
  onSuccess: () => void;
}) {
  const [clientSecret, setClientSecret] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    fetch("/api/stripe/create-subscription", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ walletAddress }),
    })
      .then((r) => r.json())
      .then((data) => {
        if (data.clientSecret) setClientSecret(data.clientSecret);
        else setError("Could not initialize payment");
      })
      .catch(() => setError("Could not initialize payment"));
  }, [walletAddress]);

  if (error) {
    return <p className="font-body text-sm text-red-600 text-center">{error}</p>;
  }

  if (!clientSecret) {
    return (
      <p className="font-body text-sm text-zinc-400 text-center">Loading…</p>
    );
  }

  return (
    <Elements
      stripe={stripePromise}
      options={{
        clientSecret,
        appearance: {
          theme: "stripe",
          variables: {
            fontFamily: "Arial, Helvetica, sans-serif",
            colorPrimary: "#000000",
            borderRadius: "8px",
          },
        },
      }}
    >
      <StripeForm onSuccess={onSuccess} />
    </Elements>
  );
}

function StripeForm({ onSuccess }: { onSuccess: () => void }) {
  const stripe = useStripe();
  const elements = useElements();
  const [processing, setProcessing] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!stripe || !elements) return;
    setProcessing(true);
    setError(null);

    const { error: confirmError } = await stripe.confirmPayment({
      elements,
      redirect: "if_required",
    });

    if (confirmError) {
      setError(confirmError.message || "Payment failed");
      setProcessing(false);
    } else {
      onSuccess();
    }
  };

  return (
    <form onSubmit={submit} className="space-y-4">
      <PaymentElement
        options={{
          layout: "tabs",
          paymentMethodOrder: ["apple_pay", "google_pay", "card"],
        }}
      />
      {error && (
        <p className="font-body text-sm text-red-600">{error}</p>
      )}
      <button
        type="submit"
        disabled={!stripe || processing}
        className="w-full font-title font-bold py-3 rounded-lg bg-black text-white hover:bg-zinc-800 disabled:opacity-50 transition"
      >
        {processing ? "Processing…" : `Subscribe for ${PRICE_DISPLAY}/${INTERVAL_DISPLAY}`}
      </button>
    </form>
  );
}
