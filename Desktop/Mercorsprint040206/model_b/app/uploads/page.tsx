"use client";

import { useRef, useState } from "react";
import dynamic from "next/dynamic";
import Link from "next/link";

const MuxUploader = dynamic(() => import("@mux/mux-uploader-react"), {
  ssr: false,
});

export default function UploadsPage() {
  const [title, setTitle] = useState("");
  const [description, setDescription] = useState("");
  const [date, setDate] = useState(new Date().toISOString().slice(0, 10));
  const [status, setStatus] = useState<
    "idle" | "uploading" | "uploaded" | "saved" | "error"
  >("idle");
  const [msg, setMsg] = useState<string | null>(null);
  const [demo, setDemo] = useState(false);

  const uploadIdRef = useRef<string | null>(null);
  const adminSecretRef = useRef<string>("");

  function adminHeaders(): HeadersInit {
    if (!adminSecretRef.current && typeof window !== "undefined") {
      adminSecretRef.current = sessionStorage.getItem("adminSecret") || "";
    }
    return adminSecretRef.current
      ? { "x-admin-secret": adminSecretRef.current }
      : {};
  }

  function promptSecret() {
    const s = window.prompt("Admin secret");
    if (s) {
      adminSecretRef.current = s;
      sessionStorage.setItem("adminSecret", s);
    }
    return !!s;
  }

  // MuxUploader calls this when a file is selected to get the direct-upload URL.
  async function getEndpoint(): Promise<string> {
    let r = await fetch("/api/mux/upload", {
      method: "POST",
      headers: adminHeaders(),
    });
    if (r.status === 401 && promptSecret()) {
      r = await fetch("/api/mux/upload", {
        method: "POST",
        headers: adminHeaders(),
      });
    }
    if (r.status === 401) throw new Error("unauthorized");
    const d = await r.json();
    uploadIdRef.current = d.uploadId;
    if (d.demo) {
      setDemo(true);
      setStatus("uploaded");
      setMsg(
        "Mux keys not configured — file not sent. Fill in the details and click Save."
      );
      throw new Error("demo-mode");
    }
    return d.url as string;
  }

  async function save(e: React.FormEvent) {
    e.preventDefault();
    const r = await fetch("/api/videos", {
      method: "POST",
      headers: { "Content-Type": "application/json", ...adminHeaders() },
      body: JSON.stringify({
        title,
        description,
        date,
        uploadId: uploadIdRef.current,
        demo,
      }),
    });
    if (r.ok) {
      setStatus("saved");
      setMsg("Saved. It now appears on /videos.");
    } else if (r.status === 401) {
      setStatus("error");
      setMsg("Unauthorized — admin secret required.");
      promptSecret();
    } else {
      setStatus("error");
      setMsg("Failed to save.");
    }
  }

  return (
    <main className="container">
      <header style={{ padding: "36px 0 4px" }}>
        <h1 style={{ fontSize: 32 }}>Upload a video</h1>
        <p style={{ color: "var(--muted)" }}>
          Drop a file, add details, then save. Files go directly to Mux.
        </p>
      </header>

      <form className="upload-form" onSubmit={save}>
        <div>
          <label style={{ marginBottom: 8 }}>Video file</label>
          <MuxUploader
            endpoint={getEndpoint}
            onUploadStart={() => setStatus("uploading")}
            onSuccess={() => {
              setStatus("uploaded");
              setMsg("Upload complete. Add details and click Save.");
            }}
            onUploadError={(e: unknown) => {
              if (!demo) {
                setStatus("error");
                setMsg("Upload failed.");
                console.error(e);
              }
            }}
            style={{
              width: "100%",
              ["--button-border-radius" as string]: "999px",
            }}
          />
          {demo && (
            <div className="demo-banner" style={{ marginTop: 10 }}>
              Demo mode — set <code>MUX_TOKEN_ID</code> /{" "}
              <code>MUX_TOKEN_SECRET</code> to actually upload files.
            </div>
          )}
        </div>

        <label>
          Title
          <input
            required
            value={title}
            onChange={(e) => setTitle(e.target.value)}
            placeholder="Episode title"
          />
        </label>
        <label>
          Description
          <textarea
            required
            value={description}
            onChange={(e) => setDescription(e.target.value)}
            placeholder="What's this episode about?"
          />
        </label>
        <label>
          Date
          <input
            type="date"
            required
            value={date}
            onChange={(e) => setDate(e.target.value)}
          />
        </label>

        <button
          className="btn btn-primary"
          type="submit"
          disabled={status === "uploading"}
        >
          {status === "uploading" ? "Uploading…" : "Save video"}
        </button>

        {msg && (
          <p style={{ fontSize: 14 }}>
            <span className="status-pill">
              {status === "saved"
                ? "Saved"
                : status === "error"
                  ? "Error"
                  : "Info"}
            </span>{" "}
            {msg}{" "}
            {status === "saved" && <Link href="/videos">View on /videos →</Link>}
          </p>
        )}
      </form>
    </main>
  );
}
