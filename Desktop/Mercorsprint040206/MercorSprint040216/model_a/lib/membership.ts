import { createThirdwebClient, getContract, readContract } from "thirdweb";
import { defineChain } from "thirdweb/chains";
import { CHAIN_ID, MEMBERSHIP_CONTRACT } from "./config";

/**
 * Server-side membership check. Calls MembershipPass.isMember(address) on-chain.
 * Used by gated API routes (Mux token, etc.) to authorize requests.
 *
 * Returns null when the contract isn't deployed yet (demo mode) — callers
 * decide how to handle that.
 *
 * SECURITY NOTE: this verifies the address HOLDS a pass, not that the
 * requester CONTROLS that address. For production, gate the playback-token
 * endpoint behind ThirdWeb Auth (SIWE) so the wallet address comes from a
 * verified session JWT, not a request body anyone can forge.
 */
export async function checkMembershipOnChain(
  address: string
): Promise<boolean | null> {
  const clientId = process.env.NEXT_PUBLIC_THIRDWEB_CLIENT_ID;
  const secretKey = process.env.THIRDWEB_SECRET_KEY;

  if (!MEMBERSHIP_CONTRACT || (!clientId && !secretKey)) {
    return null; // contract not deployed / no client → caller handles demo
  }

  // Prefer secretKey for server-side reads (no rate limits).
  const client = secretKey
    ? createThirdwebClient({ secretKey })
    : createThirdwebClient({ clientId: clientId! });

  const contract = getContract({
    client,
    chain: defineChain(CHAIN_ID),
    address: MEMBERSHIP_CONTRACT,
  });

  return readContract({
    contract,
    method: "function isMember(address account) view returns (bool)",
    params: [address],
  });
}
