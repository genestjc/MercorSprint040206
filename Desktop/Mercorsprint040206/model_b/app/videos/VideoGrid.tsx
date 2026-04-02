"use client";

import { useState } from "react";
import type { Video } from "@/lib/videos";
import { VideoCard } from "@/components/VideoCard";
import { PaywallModal } from "@/components/PaywallModal";

export function VideoGrid({
  videos,
  unlocked,
}: {
  videos: Video[];
  unlocked: boolean;
}) {
  const [showPaywall, setShowPaywall] = useState(false);

  return (
    <>
      <div className="video-grid">
        {videos.map((v) => (
          <VideoCard
            key={v.id}
            video={v}
            unlocked={unlocked}
            onLockedClick={() => setShowPaywall(true)}
          />
        ))}
      </div>

      {showPaywall && !unlocked && (
        <PaywallModal onClose={() => setShowPaywall(false)} />
      )}
    </>
  );
}
