import { createThirdwebClient } from "thirdweb";
import { defineChain } from "thirdweb/chains";
import { CHAIN_ID } from "./config";

/**
 * Client is created lazily so the app boots in demo mode without a clientId.
 * Components must check `clientDemo.thirdweb` before rendering ThirdWeb UI.
 */
export const thirdwebClient = process.env.NEXT_PUBLIC_THIRDWEB_CLIENT_ID
  ? createThirdwebClient({
      clientId: process.env.NEXT_PUBLIC_THIRDWEB_CLIENT_ID,
    })
  : null;

export const chain = defineChain(CHAIN_ID);
