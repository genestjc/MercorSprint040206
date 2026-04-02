/**
 * Demo-mode detection. Each integration falls back independently —
 * add Stripe keys first and test real payments while Mux/ThirdWeb stay mocked.
 *
 * Server-only flags read secret keys; client flags are derived from
 * NEXT_PUBLIC_* vars and exposed via /api/videos.
 */

// Server-side flags (do NOT import from client components)
export const serverDemo = {
  stripe: !process.env.STRIPE_SECRET_KEY,
  mux: !process.env.MUX_TOKEN_ID || !process.env.MUX_TOKEN_SECRET,
  thirdweb: !process.env.THIRDWEB_SECRET_KEY,
};

// Client-safe flags (NEXT_PUBLIC_* only — inlined at build time)
export const clientDemo = {
  stripe: !process.env.NEXT_PUBLIC_STRIPE_PUBLISHABLE_KEY,
  thirdweb: !process.env.NEXT_PUBLIC_THIRDWEB_CLIENT_ID,
};

export const STRIPE_PRICE_ID = process.env.STRIPE_PRICE_ID;
export const MEMBERSHIP_CONTRACT =
  process.env.NEXT_PUBLIC_MEMBERSHIP_CONTRACT_ADDRESS;
export const CHAIN_ID = Number(process.env.NEXT_PUBLIC_CHAIN_ID || 84532); // Base Sepolia
