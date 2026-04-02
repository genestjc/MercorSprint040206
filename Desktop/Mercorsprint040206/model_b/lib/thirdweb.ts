import { createThirdwebClient } from "thirdweb";
import { base } from "thirdweb/chains";

export const client = createThirdwebClient({
  clientId: process.env.NEXT_PUBLIC_THIRDWEB_CLIENT_ID || "demo",
});

export const chain = base; // Base mainnet (8453)

export const MEMBERSHIP_CONTRACT =
  process.env.NEXT_PUBLIC_MEMBERSHIP_CONTRACT || "";
