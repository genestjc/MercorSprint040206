"use client";

import { useEffect, useState } from "react";
import dynamic from "next/dynamic";
import type { VideoEntry } from "@/lib/videoStore";
import { useMembership } from "./MembershipContext";

const MuxPlayer = dynamic(() => import("@mux/mux-player-react"), {
  ssr: false,
});

interface Props {
  video: VideoEntry;
  locked: boolean;
  onLockedClick: () => void;
}

/**
 * When unlocked, fetches a signed playback token before mounting the player.
 * The token endpoint verifies NFT ownership on-chain — so even if someone
 * pulls the playbackId from this component's source, they can't watch
 * without holding a pass.
 *
 * Demo mode (no MUX_SIGNING_KEY): endpoint returns { demo: true } and we
 * play directly via the public playback ID. The seed videos use Mux's
 * public test asset.
 */
export function VideoCard({ video, locked, onLockedClick }: Props) {
  const { walletAddress } = useMembership();
  const [tokens, setTokens] = useState<{
    playbackToken?: string;
    thumbnailToken?: string;
    demo?: boolean;
  } | null>(null);
  const [tokenError, setTokenError] = useState<string | null>(null);

  // Fetch tokens once unlocked
  useEffect(() => {
    if (locked || !walletAddress) {
      setTokens(null);
      return;
    }
    let cancelled = false;
    setTokenError(null);

    fetch("/api/mux/playback-token", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ playbackId: video.playbackId, walletAddress }),
    })
      .then(async (r) => {
        if (!r.ok) throw new Error((await r.json()).error || "Token denied");
        return r.json();
      })
      .then((data) => !cancelled && setTokens(data))
      .catch((e) => !cancelled && setTokenError(String(e.message || e)));

    return () => {
      cancelled = true;
    };
  }, [locked, walletAddress, video.playbackId]);

  // ── Thumbnail URL ─────────────────────────────────────────────────────────
  // Locked or demo: use public thumbnail (works for the seed test asset).
  // Real signed assets: thumbnails also need a token, but for the *locked*
  // preview we'd ideally store a separate public thumbnail. For now we try
  // public and accept that real signed assets show a black tile when locked.
  const thumbBase = `https://image.mux.com/${video.playbackId}/thumbnail.jpg?width=640&time=1`;
  const thumb =
    !locked && tokens?.thumbnailToken
      ? `${thumbBase}&token=${tokens.thumbnailToken}`
      : thumbBase;

  return (
    <div className="group rounded-lg overflow-hidden border border-zinc-200 bg-white">
      <div className="relative aspect-video bg-zinc-900">
        {locked ? (
          <button
            onClick={onLockedClick}
            className="absolute inset-0 w-full h-full"
          >
            {/* eslint-disable-next-line @next/next/no-img-element */}
            <img
              src={thumb}
              alt={video.title}
              className="absolute inset-0 w-full h-full object-cover blur-sm scale-105 opacity-70"
            />
            <div className="absolute inset-0 bg-gradient-to-t from-black/60 to-black/20" />
            <div className="relative flex flex-col items-center justify-center h-full text-white">
              <svg
                className="w-10 h-10 mb-2"
                fill="none"
                viewBox="0 0 24 24"
                stroke="currentColor"
                strokeWidth={2}
              >
                <rect x="5" y="11" width="14" height="10" rx="2" />
                <path d="M8 11V7a4 4 0 0 1 8 0v4" />
              </svg>
              <span className="font-title font-bold text-sm tracking-wide">
                Members only
              </span>
            </div>
          </button>
        ) : tokenError ? (
          <div className="absolute inset-0 flex items-center justify-center text-white">
            <p className="font-body text-xs text-red-300 px-4 text-center">
              {tokenError}
            </p>
          </div>
        ) : !tokens ? (
          <div className="absolute inset-0 flex items-center justify-center text-zinc-500">
            <span className="font-body text-xs">Loading…</span>
          </div>
        ) : (
          <MuxPlayer
            playbackId={video.playbackId}
            tokens={
              tokens.demo
                ? undefined
                : {
                    playback: tokens.playbackToken,
                    thumbnail: tokens.thumbnailToken,
                  }
            }
            metadata={{ video_title: video.title }}
            streamType="on-demand"
            className="absolute inset-0 w-full h-full"
          />
        )}
      </div>

      <div className="p-4">
        <h3 className="font-title font-bold text-lg leading-tight mb-1">
          {video.title}
        </h3>
        <p className="font-body text-sm text-zinc-600 line-clamp-2 mb-2">
          {video.description}
        </p>
        <p className="font-body text-xs text-zinc-400">
          {new Date(video.date).toLocaleDateString("en-US", {
            month: "long",
            day: "numeric",
            year: "numeric",
          })}
        </p>
      </div>
    </div>
  );
}
