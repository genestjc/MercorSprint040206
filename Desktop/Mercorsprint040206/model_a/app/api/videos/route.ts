import { NextRequest, NextResponse } from "next/server";
import { listVideos, addVideo, VideoEntry } from "@/lib/videoStore";
import { getMux } from "@/lib/mux";
import { serverDemo } from "@/lib/config";

// Mux's public test asset — plays without credentials.
const DEMO_PLAYBACK_ID = "VZtzUzGRv02OhRnZCxcNg49OilvolTqdnFLEqBsTwaxU";

export async function GET() {
  const videos = await listVideos();
  return NextResponse.json({
    videos,
    demo: {
      stripe: serverDemo.stripe,
      mux: serverDemo.mux,
      thirdweb: serverDemo.thirdweb,
    },
  });
}

export async function POST(req: NextRequest) {
  const body = await req.json();
  const { title, description, date, uploadId } = body;

  if (!title || !date) {
    return NextResponse.json(
      { error: "title and date are required" },
      { status: 400 }
    );
  }

  let playbackId = DEMO_PLAYBACK_ID;

  // If we have Mux credentials and an uploadId, resolve the real playback ID.
  const mux = getMux();
  if (mux && uploadId) {
    const upload = await mux.video.uploads.retrieve(uploadId);
    if (upload.asset_id) {
      const asset = await mux.video.assets.retrieve(upload.asset_id);
      // Prefer signed playback IDs (paywall enforceable); fall back to public.
      const pid =
        asset.playback_ids?.find((p) => p.policy === "signed") ||
        asset.playback_ids?.[0];
      if (pid) playbackId = pid.id;
    }
  }

  const entry: VideoEntry = {
    id: crypto.randomUUID(),
    title,
    description: description || "",
    date,
    playbackId,
    uploadId,
  };

  await addVideo(entry);
  return NextResponse.json({ video: entry });
}
