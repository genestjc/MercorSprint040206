import { promises as fs } from "fs";
import path from "path";

export type Video = {
  id: string;
  title: string;
  description: string;
  date: string; // ISO yyyy-mm-dd
  playbackId?: string; // Mux playback id once asset is ready
  uploadId?: string; // Mux upload id while processing
  demo?: boolean;
};

const FILE = path.join(process.cwd(), "data", "videos.json");

const SEED: Video[] = [
  {
    id: "seed-1",
    title: "Inside the Studio: Episode 1",
    description: "A behind-the-scenes look at how we build. Members only.",
    date: "2026-03-12",
    demo: true,
  },
  {
    id: "seed-2",
    title: "Founder Q&A — March",
    description: "Live questions from the community, answered.",
    date: "2026-03-20",
    demo: true,
  },
  {
    id: "seed-3",
    title: "Deep Dive: On-Chain Membership",
    description: "How your subscription becomes a Base NFT.",
    date: "2026-03-27",
    demo: true,
  },
  {
    id: "seed-4",
    title: "Roadmap Preview",
    description: "What's shipping next quarter.",
    date: "2026-04-01",
    demo: true,
  },
];

export async function readVideos(): Promise<Video[]> {
  try {
    const raw = await fs.readFile(FILE, "utf8");
    const stored: Video[] = JSON.parse(raw);
    return [...stored, ...SEED];
  } catch {
    return SEED;
  }
}

export async function appendVideo(v: Omit<Video, "id">): Promise<Video> {
  let stored: Video[] = [];
  try {
    stored = JSON.parse(await fs.readFile(FILE, "utf8"));
  } catch {
    /* empty */
  }
  const video: Video = { id: `v-${Date.now()}`, ...v };
  stored.unshift(video);
  await fs.writeFile(FILE, JSON.stringify(stored, null, 2));
  return video;
}
