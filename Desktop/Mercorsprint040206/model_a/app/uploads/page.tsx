"use client";

import { useState, useRef } from "react";
import dynamic from "next/dynamic";
import { useRouter } from "next/navigation";

const MuxUploader = dynamic(() => import("@mux/mux-uploader-react"), {
  ssr: false,
});

export default function UploadsPage() {
  const router = useRouter();
  const [title, setTitle] = useState("");
  const [description, setDescription] = useState("");
  const [date, setDate] = useState(new Date().toISOString().slice(0, 10));
  const [muxDemo, setMuxDemo] = useState(false);
  const [uploadDone, setUploadDone] = useState(false);
  const [saving, setSaving] = useState(false);
  const [success, setSuccess] = useState(false);
  const uploadIdRef = useRef<string | null>(null);

  // MuxUploader calls this to get the direct-upload URL.
  // If our API returns { demo: true }, switch to demo mode and skip the upload.
  const fetchUploadUrl = async (): Promise<string> => {
    const res = await fetch("/api/mux/upload-url", { method: "POST" });
    const data = await res.json();
    if (data.demo) {
      setMuxDemo(true);
      setUploadDone(true);
      return Promise.reject(new Error("demo-mode"));
    }
    uploadIdRef.current = data.uploadId;
    return data.url;
  };

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setSaving(true);

    const res = await fetch("/api/videos", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        title,
        description,
        date,
        uploadId: uploadIdRef.current,
      }),
    });

    setSaving(false);
    if (res.ok) {
      setSuccess(true);
      setTimeout(() => router.push("/videos"), 1200);
    }
  };

  const canSubmit = title && date && (uploadDone || muxDemo);

  return (
    <div className="max-w-2xl mx-auto px-6 py-12">
      <h1 className="font-title font-bold text-3xl tracking-tight mb-2">
        Upload a video
      </h1>
      <p className="font-body text-zinc-600 mb-8">
        Add a new video to the library. It will appear on /videos once saved.
      </p>

      <form onSubmit={submit} className="space-y-6">
        {/* ── Mux upload ──────────────────────────────────────────────── */}
        <div>
          <label className="font-title font-bold text-sm block mb-2">
            Video file
          </label>
          {muxDemo ? (
            <div className="border-2 border-dashed border-zinc-300 rounded-lg p-8 text-center">
              <p className="font-body text-sm text-zinc-500">
                Mux is in demo mode — no real upload will occur.
                <br />
                A test video will be used as a placeholder.
              </p>
            </div>
          ) : (
            <div className="border border-zinc-200 rounded-lg overflow-hidden">
              <MuxUploader
                endpoint={fetchUploadUrl}
                onSuccess={() => setUploadDone(true)}
                style={{ fontFamily: "Arial, sans-serif" } as React.CSSProperties}
              />
            </div>
          )}
          {uploadDone && !muxDemo && (
            <p className="font-body text-xs text-green-600 mt-2">
              ✓ Upload complete
            </p>
          )}
        </div>

        {/* ── Metadata ────────────────────────────────────────────────── */}
        <div>
          <label className="font-title font-bold text-sm block mb-2">
            Title
          </label>
          <input
            type="text"
            value={title}
            onChange={(e) => setTitle(e.target.value)}
            required
            className="w-full font-body px-4 py-2.5 border border-zinc-300 rounded-lg focus:border-black focus:outline-none"
          />
        </div>

        <div>
          <label className="font-title font-bold text-sm block mb-2">
            Description
          </label>
          <textarea
            value={description}
            onChange={(e) => setDescription(e.target.value)}
            rows={4}
            className="w-full font-body px-4 py-2.5 border border-zinc-300 rounded-lg focus:border-black focus:outline-none resize-none"
          />
        </div>

        <div>
          <label className="font-title font-bold text-sm block mb-2">
            Date
          </label>
          <input
            type="date"
            value={date}
            onChange={(e) => setDate(e.target.value)}
            required
            className="font-body px-4 py-2.5 border border-zinc-300 rounded-lg focus:border-black focus:outline-none"
          />
        </div>

        <button
          type="submit"
          disabled={!canSubmit || saving}
          className="w-full font-title font-bold py-3 rounded-lg bg-black text-white hover:bg-zinc-800 disabled:opacity-40 disabled:cursor-not-allowed transition"
        >
          {saving ? "Saving…" : success ? "✓ Saved" : "Save video"}
        </button>
      </form>
    </div>
  );
}
