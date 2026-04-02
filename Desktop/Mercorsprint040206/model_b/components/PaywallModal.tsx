"use client";

import { useEffect, useMemo, useState } from "react";
import { useRouter } from "next/navigation";
import { loadStripe, type Appearance } from "@stripe/stripe-js";
import {
  Elements,
  PaymentElement,
  useElements,
  useStripe,
} from "@stripe/react-stripe-js";
import { ConnectEmbed, useActiveAccount } from "thirdweb/react";
import { inAppWallet, createWallet } from "thirdweb/wallets";
import { client, chain } from "@/lib/thirdweb";

const PUBLISHABLE = process.env.NEXT_PUBLIC_STRIPE_PUBLISHABLE_KEY;
const stripePromise = PUBLISHABLE ? loadStripe(PUBLISHABLE) : null;

const appearance: Appearance = {
  theme: "stripe",
  variables: {
    fontFamily: "Arial, sans-serif",
    colorPrimary: "#111111",
    borderRadius: "8px",
  },
  rules: { ".Label": { fontFamily: "Arial, sans-serif" } },
};

const wallets = [
  inAppWallet({
    auth: {
      options: ["google", "apple", "facebook", "discord", "email", "passkey"],
    },
  }),
  createWallet("io.metamask"),
  createWallet("com.coinbase.wallet"),
];

function short(addr: string) {
  return `${addr.slice(0, 6)}…${addr.slice(-4)}`;
}

function CheckoutForm() {
  const stripe = useStripe();
  const elements = useElements();
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  return (
    <form
      onSubmit={async (e) => {
        e.preventDefault();
        if (!stripe || !elements) return;
        setBusy(true);
        setErr(null);
        const { error } = await stripe.confirmPayment({
          elements,
          confirmParams: {
            return_url: `${window.location.origin}/api/stripe/confirm`,
          },
        });
        if (error) {
          setErr(error.message ?? "Payment failed");
          setBusy(false);
        }
      }}
    >
      <PaymentElement
        options={{
          layout: "tabs",
          wallets: { applePay: "auto", googlePay: "auto" },
        }}
      />
      {err && (
        <p style={{ color: "#b91c1c", fontSize: 13, marginTop: 10 }}>{err}</p>
      )}
      <button
        className="btn btn-primary"
        disabled={!stripe || busy}
        style={{ width: "100%", marginTop: 18 }}
      >
        {busy ? "Processing…" : "Subscribe"}
      </button>
    </form>
  );
}

function PaymentStep({ walletAddress }: { walletAddress: string }) {
  const router = useRouter();
  const [clientSecret, setClientSecret] = useState<string | null>(null);
  const [demo, setDemo] = useState(!PUBLISHABLE);
  const [loading, setLoading] = useState(!!PUBLISHABLE);

  useEffect(() => {
    if (!PUBLISHABLE) return;
    fetch("/api/stripe/create-subscription", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ walletAddress }),
    })
      .then((r) => r.json())
      .then((d) => {
        if (d.demo || d.error) setDemo(true);
        else setClientSecret(d.clientSecret);
      })
      .catch(() => setDemo(true))
      .finally(() => setLoading(false));
  }, [walletAddress]);

  const options = useMemo(
    () => (clientSecret ? { clientSecret, appearance } : undefined),
    [clientSecret]
  );

  async function simulate() {
    await fetch("/api/access/demo", { method: "POST" });
    router.refresh();
  }

  return (
    <>
      <div
        style={{
          display: "flex",
          justifyContent: "space-between",
          alignItems: "center",
          padding: "10px 12px",
          background: "#f6f6f6",
          borderRadius: 8,
          margin: "0 0 16px",
          fontSize: 13,
        }}
      >
        <span style={{ color: "var(--muted)" }}>Minting to</span>
        <code>{short(walletAddress)}</code>
      </div>

      <ul className="benefits">
        <li>Unlimited streaming of all member videos</li>
        <li>On-chain Membership Pass NFT (Base)</li>
        <li>New episodes every week</li>
      </ul>

      {demo ? (
        <>
          <div className="demo-banner">
            Demo mode — Stripe keys not configured. Use the button below to
            simulate a successful subscription.
          </div>
          <button
            className="btn btn-primary"
            style={{ width: "100%" }}
            onClick={simulate}
          >
            Simulate subscription
          </button>
        </>
      ) : loading ? (
        <p style={{ textAlign: "center", color: "#6b6b6b" }}>
          Loading secure checkout…
        </p>
      ) : options && stripePromise ? (
        <Elements stripe={stripePromise} options={options}>
          <CheckoutForm />
        </Elements>
      ) : null}
    </>
  );
}

export function PaywallModal({ onClose }: { onClose: () => void }) {
  const account = useActiveAccount();
  const step = account ? 2 : 1;

  return (
    <div className="modal-backdrop" onClick={onClose}>
      <div className="modal" onClick={(e) => e.stopPropagation()}>
        <button className="close" onClick={onClose} aria-label="Close">
          ×
        </button>

        <div className="kicker">Step {step} of 2 · Membership</div>
        <h2 className="headline">
          {step === 1 ? "Sign in to continue." : "Unlock every video."}
        </h2>
        <p className="sub">
          {step === 1
            ? "Your Membership Pass NFT will be minted to this account on Base."
            : "Cancel anytime. $9 / month."}
        </p>

        {step === 1 ? (
          <ConnectEmbed
            client={client}
            chain={chain}
            wallets={wallets}
            theme="light"
            showThirdwebBranding={false}
            style={{ width: "100%", border: "none", padding: 0 }}
          />
        ) : (
          <PaymentStep walletAddress={account!.address} />
        )}

        <p className="fineprint">
          By subscribing you agree to our Terms. Renews monthly until
          cancelled.
        </p>
      </div>
    </div>
  );
}
