import { readVideos } from "@/lib/videos";
import { hasAccess } from "@/lib/access";
import { VideoGrid } from "./VideoGrid";
import { ResetMembership } from "./ResetMembership";

export const dynamic = "force-dynamic";

export default async function VideosPage() {
  const [videos, unlocked] = await Promise.all([readVideos(), hasAccess()]);

  return (
    <main className="container">
      <header style={{ padding: "36px 0 8px" }}>
        <h1 style={{ fontSize: 36 }}>Videos</h1>
        <p style={{ color: "var(--muted)", maxWidth: 560 }}>
          {unlocked
            ? "Welcome back, member. Enjoy unlimited access."
            : "Premium episodes for members. Sign in and subscribe to unlock."}
        </p>
        {unlocked && (
          <div style={{ marginTop: 10, display: "flex", gap: 12, alignItems: "center" }}>
            <span className="status-pill">Member · Unlocked</span>
            <ResetMembership />
          </div>
        )}
      </header>

      <VideoGrid videos={videos} unlocked={unlocked} />
    </main>
  );
}
