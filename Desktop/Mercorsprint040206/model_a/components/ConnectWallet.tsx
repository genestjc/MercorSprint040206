"use client";

import { ConnectButton, useActiveAccount } from "thirdweb/react";
import { inAppWallet, createWallet } from "thirdweb/wallets";
import { thirdwebClient, chain } from "@/lib/thirdweb";
import { clientDemo } from "@/lib/config";
import { useMembership } from "./MembershipContext";

/**
 * Top-right sign-in. When NEXT_PUBLIC_THIRDWEB_CLIENT_ID is set, renders
 * ThirdWeb's ConnectButton with social login (Google/Apple/Email embedded
 * wallet). In demo mode, a simple localStorage-backed button.
 */

const wallets = [
  inAppWallet({
    auth: { options: ["google", "apple", "email", "passkey"] },
  }),
  createWallet("io.metamask"),
  createWallet("com.coinbase.wallet"),
];

export function ConnectWallet() {
  const { isSignedIn, walletAddress, signInDemo, signOutDemo } = useMembership();
  const account = useActiveAccount();

  // Real ThirdWeb mode
  if (!clientDemo.thirdweb && thirdwebClient) {
    return (
      <ConnectButton
        client={thirdwebClient}
        wallets={wallets}
        chain={chain}
        connectButton={{
          label: "Sign In",
          className: "!font-title !font-bold",
        }}
        connectModal={{
          title: "Sign in to continue",
          titleIcon: "",
          size: "compact",
        }}
        theme="light"
      />
    );
  }

  // Demo fallback
  if (isSignedIn || account) {
    const display = walletAddress || "";
    return (
      <button
        onClick={signOutDemo}
        className="font-body text-sm px-4 py-2 rounded-full bg-zinc-100 hover:bg-zinc-200 transition"
        title="Click to sign out"
      >
        {display.slice(0, 6)}…{display.slice(-4)}
      </button>
    );
  }

  return (
    <button
      onClick={signInDemo}
      className="font-title font-bold text-sm px-5 py-2 rounded-full bg-black text-white hover:bg-zinc-800 transition"
    >
      Sign In
    </button>
  );
}
