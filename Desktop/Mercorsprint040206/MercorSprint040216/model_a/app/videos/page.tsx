"use client";

import { useEffect, useState } from "react";
import { VideoCard } from "@/components/VideoCard";
import { PaywallModal } from "@/components/PaywallModal";
import { useMembership } from "@/components/MembershipContext";
import type { VideoEntry } from "@/lib/videoStore";

interface DemoFlags {
  stripe: boolean;
  mux: boolean;
  thirdweb: boolean;
}

export default function VideosPage() {
  const { isMember } = useMembership();
  const [videos, setVideos] = useState<VideoEntry[]>([]);
  const [demo, setDemo] = useState<DemoFlags | null>(null);
  const [paywallOpen, setPaywallOpen] = useState(false);

  useEffect(() => {
    fetch("/api/videos")
      .then((r) => r.json())
      .then((data) => {
        setVideos(data.videos);
        setDemo(data.demo);
      });
  }, []);

  const anyDemo = demo && (demo.stripe || demo.mux || demo.thirdweb);

  return (
    <>
      <div className="max-w-6xl mx-auto px-6 py-12">
        <div className="mb-10">
          <h1 className="font-title font-bold text-4xl tracking-tight mb-3">
            Video Library
          </h1>
          <p className="font-body text-zinc-600 max-w-2xl">
            {isMember
              ? "Welcome back. Enjoy unlimited access to every video."
              : "Subscribe to unlock our full collection of member-only videos."}
          </p>

          {anyDemo && (
            <div className="mt-4 inline-flex flex-wrap gap-2">
              {demo!.stripe && <DemoBadge label="Stripe" />}
              {demo!.mux && <DemoBadge label="Mux" />}
              {demo!.thirdweb && <DemoBadge label="ThirdWeb" />}
            </div>
          )}
        </div>

        {videos.length === 0 ? (
          <p className="font-body text-zinc-400">
            No videos yet. Add one from{" "}
            <a href="/uploads" className="underline">
              /uploads
            </a>
            .
          </p>
        ) : (
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
            {videos.map((v) => (
              <VideoCard
                key={v.id}
                video={v}
                locked={!isMember}
                onLockedClick={() => setPaywallOpen(true)}
              />
            ))}
          </div>
        )}
      </div>

      <PaywallModal open={paywallOpen} onClose={() => setPaywallOpen(false)} />
    </>
  );
}

function DemoBadge({ label }: { label: string }) {
  return (
    <span className="font-body text-xs px-2.5 py-1 rounded-full bg-amber-100 text-amber-800 border border-amber-200">
      {label}: demo mode
    </span>
  );
}
