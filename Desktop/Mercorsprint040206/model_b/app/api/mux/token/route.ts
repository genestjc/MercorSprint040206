import { NextRequest, NextResponse } from "next/server";
import Mux from "@mux/mux-node";
import { hasAccess } from "@/lib/access";

/**
 * Issues short-lived signed playback tokens for Mux. Only members get one.
 * Requires MUX_SIGNING_KEY_ID and MUX_SIGNING_KEY_SECRET (base64 private key)
 * — create these in the Mux dashboard under Settings → Signing Keys.
 */
export async function GET(req: NextRequest) {
  if (!(await hasAccess())) {
    return NextResponse.json({ error: "Unauthorized" }, { status: 401 });
  }

  const playbackId = req.nextUrl.searchParams.get("playbackId");
  if (!playbackId) {
    return NextResponse.json({ error: "playbackId required" }, { status: 400 });
  }

  const keyId = process.env.MUX_SIGNING_KEY_ID;
  const keySecret = process.env.MUX_SIGNING_KEY_SECRET;
  if (!keyId || !keySecret) {
    return NextResponse.json({ demo: true });
  }

  const mux = new Mux({
    tokenId: process.env.MUX_TOKEN_ID,
    tokenSecret: process.env.MUX_TOKEN_SECRET,
    jwtSigningKey: { keyId, keySecret },
  });

  const [playback, thumbnail] = await Promise.all([
    mux.jwt.signPlaybackId(playbackId, { type: "video", expiration: "6h" }),
    mux.jwt.signPlaybackId(playbackId, { type: "thumbnail", expiration: "6h" }),
  ]);

  return NextResponse.json({ playback, thumbnail });
}
