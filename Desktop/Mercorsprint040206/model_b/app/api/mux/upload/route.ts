import { NextRequest, NextResponse } from "next/server";
import { mux, muxConfigured } from "@/lib/mux";
import { isAdmin } from "@/lib/admin";

export async function POST(req: NextRequest) {
  if (!isAdmin(req)) {
    return NextResponse.json({ error: "Unauthorized" }, { status: 401 });
  }
  if (!muxConfigured || !mux) {
    return NextResponse.json({
      demo: true,
      uploadId: `demo-${Date.now()}`,
    });
  }

  const upload = await mux.video.uploads.create({
    cors_origin: process.env.NEXT_PUBLIC_BASE_URL || "*",
    new_asset_settings: {
      playback_policy: ["signed"],
      encoding_tier: "baseline",
    },
  });

  return NextResponse.json({ url: upload.url, uploadId: upload.id });
}
