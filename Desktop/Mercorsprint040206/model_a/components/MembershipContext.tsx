"use client";

import {
  createContext,
  useContext,
  useState,
  useEffect,
  useCallback,
  ReactNode,
} from "react";
import { useActiveAccount } from "thirdweb/react";
import { getContract, readContract } from "thirdweb";
import { thirdwebClient, chain } from "@/lib/thirdweb";
import { MEMBERSHIP_CONTRACT } from "@/lib/config";

/**
 * Membership state with three sources, in priority order:
 *
 *   1. Optimistic flag (localStorage) — set immediately on payment success.
 *      Covers the ~30s gap between confirmPayment and the mint tx landing.
 *      Cleared once the chain confirms.
 *
 *   2. On-chain — MembershipPass.isMember(address). Source of truth.
 *      Polled on connect and after payment. If this says true, the
 *      optimistic flag is cleared (no longer needed).
 *
 *   3. Demo wallet (localStorage) — fallback when no ThirdWeb client ID.
 */

interface MembershipState {
  isSignedIn: boolean;
  isMember: boolean;
  walletAddress: string | null;
  checking: boolean;
  signInDemo: () => void;
  signOutDemo: () => void;
  grantMembership: () => void; // optimistic — call right after payment
  refreshMembership: () => Promise<void>; // re-poll chain
}

const Ctx = createContext<MembershipState | null>(null);

const LS_WALLET = "demo:wallet";
const LS_OPTIMISTIC = "membership:optimistic";

export function MembershipProvider({ children }: { children: ReactNode }) {
  const account = useActiveAccount();

  const [demoWallet, setDemoWallet] = useState<string | null>(null);
  const [optimistic, setOptimistic] = useState(false);
  const [onChain, setOnChain] = useState(false);
  const [checking, setChecking] = useState(false);

  // Hydrate localStorage on mount
  useEffect(() => {
    setDemoWallet(localStorage.getItem(LS_WALLET));
    setOptimistic(localStorage.getItem(LS_OPTIMISTIC) === "true");
  }, []);

  const walletAddress = account?.address || demoWallet;

  // ── On-chain check ────────────────────────────────────────────────────────
  const checkChain = useCallback(async (address: string) => {
    if (!thirdwebClient || !MEMBERSHIP_CONTRACT) {
      // No contract deployed yet — chain check is a no-op, optimistic flag
      // is the only signal. This keeps the demo working.
      return;
    }
    setChecking(true);
    try {
      const contract = getContract({
        client: thirdwebClient,
        chain,
        address: MEMBERSHIP_CONTRACT,
      });
      const result = await readContract({
        contract,
        method: "function isMember(address account) view returns (bool)",
        params: [address],
      });
      setOnChain(result);
      // Chain confirmed → optimistic flag served its purpose, clear it.
      if (result) {
        localStorage.removeItem(LS_OPTIMISTIC);
        setOptimistic(false);
      }
    } catch (err) {
      console.warn("[membership] chain check failed:", err);
    } finally {
      setChecking(false);
    }
  }, []);

  // Check on connect / address change
  useEffect(() => {
    if (account?.address) {
      checkChain(account.address);
    } else {
      setOnChain(false);
    }
  }, [account?.address, checkChain]);

  // ── Actions ───────────────────────────────────────────────────────────────
  const signInDemo = () => {
    const addr = "0xDEMO" + Math.random().toString(16).slice(2, 10);
    localStorage.setItem(LS_WALLET, addr);
    setDemoWallet(addr);
  };

  const signOutDemo = () => {
    localStorage.removeItem(LS_WALLET);
    localStorage.removeItem(LS_OPTIMISTIC);
    setDemoWallet(null);
    setOptimistic(false);
    setOnChain(false);
  };

  const grantMembership = () => {
    // Optimistic: unlock immediately. Chain will catch up via webhook mint.
    localStorage.setItem(LS_OPTIMISTIC, "true");
    setOptimistic(true);
    // Kick off a poll so we flip to chain-confirmed as soon as the tx lands.
    if (account?.address) {
      // Poll a few times with backoff — mint tx typically lands in 5-30s.
      const addr = account.address;
      const delays = [5000, 10000, 20000, 30000];
      delays.forEach((d) => setTimeout(() => checkChain(addr), d));
    }
  };

  const refreshMembership = useCallback(async () => {
    if (account?.address) await checkChain(account.address);
  }, [account?.address, checkChain]);

  return (
    <Ctx.Provider
      value={{
        isSignedIn: !!walletAddress,
        isMember: onChain || optimistic,
        walletAddress,
        checking,
        signInDemo,
        signOutDemo,
        grantMembership,
        refreshMembership,
      }}
    >
      {children}
    </Ctx.Provider>
  );
}

export function useMembership() {
  const ctx = useContext(Ctx);
  if (!ctx)
    throw new Error("useMembership must be used within MembershipProvider");
  return ctx;
}
