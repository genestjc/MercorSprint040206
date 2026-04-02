"use client";

import { useEffect, useState } from "react";
import dynamic from "next/dynamic";
import type { Video } from "@/lib/videos";

const MuxPlayer = dynamic(() => import("@mux/mux-player-react"), {
  ssr: false,
});

type Tokens = { playback: string; thumbnail: string };

export function VideoCard({
  video,
  unlocked,
  onLockedClick,
}: {
  video: Video;
  unlocked: boolean;
  onLockedClick: () => void;
}) {
  const [tokens, setTokens] = useState<Tokens | null>(null);

  useEffect(() => {
    if (!unlocked || !video.playbackId) return;
    fetch(`/api/mux/token?playbackId=${encodeURIComponent(video.playbackId)}`)
      .then((r) => (r.ok ? r.json() : null))
      .then((d) => {
        if (d && d.playback) setTokens(d);
      })
      .catch(() => {});
  }, [unlocked, video.playbackId]);

  return (
    <article
      className="video-card"
      onClick={unlocked ? undefined : onLockedClick}
    >
      <div className={`video-thumb ${unlocked ? "" : "locked"}`}>
        <div className="poster" />
        {unlocked ? (
          video.playbackId && tokens ? (
            <MuxPlayer
              playbackId={video.playbackId}
              tokens={tokens}
              streamType="on-demand"
              style={{ position: "absolute", inset: 0, width: "100%" }}
              metadata={{ video_title: video.title }}
            />
          ) : (
            <div className="lock-overlay">
              <span className="icon">▶</span>
              <span className="label">
                {video.playbackId ? "Loading…" : "Demo Asset"}
              </span>
            </div>
          )
        ) : (
          <div className="lock-overlay">
            <span className="icon">🔒</span>
            <span className="label">Members Only</span>
          </div>
        )}
      </div>
      <div className="video-meta">
        <h3>{video.title}</h3>
        <p>{video.description}</p>
        <time dateTime={video.date}>
          {new Date(video.date).toLocaleDateString(undefined, {
            year: "numeric",
            month: "short",
            day: "numeric",
          })}
        </time>
      </div>
    </article>
  );
}
