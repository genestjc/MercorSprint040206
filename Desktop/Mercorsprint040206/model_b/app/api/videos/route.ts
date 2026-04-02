import { NextRequest, NextResponse } from "next/server";
import { readVideos, appendVideo } from "@/lib/videos";
import { mux, muxConfigured } from "@/lib/mux";
import { isAdmin } from "@/lib/admin";

export async function GET() {
  return NextResponse.json(await readVideos());
}

export async function POST(req: NextRequest) {
  if (!isAdmin(req)) {
    return NextResponse.json({ error: "Unauthorized" }, { status: 401 });
  }
  const body = await req.json();
  const { title, description, date, uploadId, demo } = body;

  if (!title || !description || !date) {
    return NextResponse.json({ error: "Missing fields" }, { status: 400 });
  }

  let playbackId: string | undefined;
  if (muxConfigured && mux && uploadId && !demo) {
    try {
      const upload = await mux.video.uploads.retrieve(uploadId);
      if (upload.asset_id) {
        const asset = await mux.video.assets.retrieve(upload.asset_id);
        playbackId = asset.playback_ids?.[0]?.id;
      }
    } catch {
      /* asset may still be processing */
    }
  }

  const video = await appendVideo({
    title,
    description,
    date,
    uploadId,
    playbackId,
    demo: !!demo,
  });

  return NextResponse.json(video, { status: 201 });
}
