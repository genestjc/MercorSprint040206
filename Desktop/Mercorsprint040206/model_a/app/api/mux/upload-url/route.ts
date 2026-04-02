import { NextResponse } from "next/server";
import { getMux } from "@/lib/mux";

/**
 * Creates a Mux direct-upload URL. <MuxUploader> on /uploads calls this
 * via its `endpoint` prop and uploads the file directly to Mux.
 *
 * Demo mode: returns { demo: true } — uploads page falls back to a
 * placeholder file input that does nothing.
 */
export async function POST() {
  const mux = getMux();

  if (!mux) {
    return NextResponse.json({ demo: true });
  }

  // Signed policy: playback IDs are useless without a JWT minted by
  // /api/mux/playback-token, which checks NFT ownership first. This is
  // what actually enforces the paywall server-side.
  const hasSigningKey =
    !!process.env.MUX_SIGNING_KEY && !!process.env.MUX_PRIVATE_KEY;

  const upload = await mux.video.uploads.create({
    new_asset_settings: {
      playback_policy: [hasSigningKey ? "signed" : "public"],
      encoding_tier: "baseline",
    },
    cors_origin: "*",
  });

  return NextResponse.json({
    url: upload.url,
    uploadId: upload.id,
  });
}
