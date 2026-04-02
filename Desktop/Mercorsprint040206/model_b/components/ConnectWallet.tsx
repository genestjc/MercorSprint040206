"use client";

import { ConnectButton } from "thirdweb/react";
import { inAppWallet, createWallet } from "thirdweb/wallets";
import { client, chain } from "@/lib/thirdweb";

const wallets = [
  inAppWallet({
    auth: {
      options: ["google", "apple", "facebook", "discord", "email", "passkey"],
    },
  }),
  createWallet("io.metamask"),
  createWallet("com.coinbase.wallet"),
];

export function ConnectWallet() {
  return (
    <ConnectButton
      client={client}
      chain={chain}
      wallets={wallets}
      theme="light"
      connectButton={{ label: "Sign in" }}
      connectModal={{
        size: "compact",
        title: "Sign in",
        showThirdwebBranding: false,
      }}
    />
  );
}
