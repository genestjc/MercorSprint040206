import {
  createThirdwebClient,
  getContract,
  prepareContractCall,
  readContract,
  sendTransaction,
} from "thirdweb";
import { base } from "thirdweb/chains";
import { privateKeyToAccount } from "thirdweb/wallets";

function ctx() {
  const secretKey = process.env.THIRDWEB_SECRET_KEY;
  const pk = process.env.BACKEND_WALLET_PK;
  const address = process.env.NEXT_PUBLIC_MEMBERSHIP_CONTRACT;
  if (!secretKey || !pk || !address) return null;

  const client = createThirdwebClient({ secretKey });
  return {
    account: privateKeyToAccount({ client, privateKey: pk }),
    contract: getContract({ client, chain: base, address }),
  };
}

/** Mint a MembershipPass to `to`. Idempotent — skips if already a member. */
export async function mintMembership(to: string): Promise<void> {
  const c = ctx();
  if (!c) {
    console.log(`[mint] skipped for ${to} — chain env not configured`);
    return;
  }
  const already = await readContract({
    contract: c.contract,
    method: "function hasPass(address) view returns (bool)",
    params: [to],
  });
  if (already) {
    console.log(`[mint] ${to} already has a pass`);
    return;
  }
  const tx = prepareContractCall({
    contract: c.contract,
    method: "function ownerMint(address to) returns (uint256)",
    params: [to],
  });
  const { transactionHash } = await sendTransaction({
    account: c.account,
    transaction: tx,
  });
  console.log(`[mint] MembershipPass → ${to}: ${transactionHash}`);
}

/** Burn the MembershipPass held by `holder`. No-op if they don't have one. */
export async function revokeMembership(holder: string): Promise<void> {
  const c = ctx();
  if (!c) {
    console.log(`[revoke] skipped for ${holder} — chain env not configured`);
    return;
  }
  const has = await readContract({
    contract: c.contract,
    method: "function hasPass(address) view returns (bool)",
    params: [holder],
  });
  if (!has) {
    console.log(`[revoke] ${holder} has no pass`);
    return;
  }
  const tx = prepareContractCall({
    contract: c.contract,
    method: "function revokeFrom(address holder)",
    params: [holder],
  });
  const { transactionHash } = await sendTransaction({
    account: c.account,
    transaction: tx,
  });
  console.log(`[revoke] MembershipPass burned for ${holder}: ${transactionHash}`);
}
