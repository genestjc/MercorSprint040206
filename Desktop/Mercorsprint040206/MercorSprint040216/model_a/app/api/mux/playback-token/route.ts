import { NextRequest, NextResponse } from "next/server";
import { getMux } from "@/lib/mux";
import { checkMembershipOnChain } from "@/lib/membership";
import { listVideos } from "@/lib/videoStore";

/**
 * Mints a short-lived Mux JWT for a signed playback ID — but only after
 * verifying the requester's wallet holds a MembershipPass NFT on-chain.
 *
 * This is what makes the paywall actually enforceable: even if someone
 * grabs a playback ID from DevTools, they can't play it without a token,
 * and they can't get a token without an NFT.
 *
 * Demo mode (no MUX_SIGNING_KEY): returns { demo: true } and the player
 * uses public playback IDs directly. The seed videos in data/videos.json
 * use Mux's public test asset, so they play without a token.
 *
 * TODO before production: replace the `walletAddress` body param with a
 * verified session (ThirdWeb Auth / SIWE). Right now anyone who knows a
 * member's address can request tokens on their behalf. Acceptable for a
 * pre-launch demo; not acceptable when money is on the line.
 */
export async function POST(req: NextRequest) {
  const mux = getMux();
  const hasSigningKey =
    !!process.env.MUX_SIGNING_KEY && !!process.env.MUX_PRIVATE_KEY;

  if (!mux || !hasSigningKey) {
    return NextResponse.json({ demo: true });
  }

  const { playbackId, walletAddress } = await req.json();

  if (!playbackId || !walletAddress) {
    return NextResponse.json(
      { error: "playbackId and walletAddress required" },
      { status: 400 }
    );
  }

  // ── Verify the playback ID is one of ours ─────────────────────────────────
  // Without this, an attacker could mint tokens for arbitrary signed assets
  // on the same Mux account.
  const videos = await listVideos();
  if (!videos.some((v) => v.playbackId === playbackId)) {
    return NextResponse.json({ error: "Unknown playback ID" }, { status: 404 });
  }

  // ── Verify membership on-chain ────────────────────────────────────────────
  const isMember = await checkMembershipOnChain(walletAddress);
  if (isMember === false) {
    return NextResponse.json({ error: "Not a member" }, { status: 403 });
  }
  // isMember === null → contract not deployed yet. We allow it through so
  // you can test signed playback before the contract is live. Tighten this
  // to a hard 403 once MEMBERSHIP_CONTRACT is set.

  // ── Sign tokens ───────────────────────────────────────────────────────────
  // Two tokens: one for video playback, one for the thumbnail (Mux requires
  // separate tokens per audience claim). 1h expiry — short enough to limit
  // sharing, long enough to watch a full video without re-fetching.
  const [playbackToken, thumbnailToken] = await Promise.all([
    mux.jwt.signPlaybackId(playbackId, { type: "video", expiration: "1h" }),
    mux.jwt.signPlaybackId(playbackId, { type: "thumbnail", expiration: "1h" }),
  ]);

  return NextResponse.json({ playbackToken, thumbnailToken });
}
