import fs from "fs/promises";
import path from "path";

export interface VideoEntry {
  id: string;
  title: string;
  description: string;
  date: string; // ISO yyyy-mm-dd
  playbackId: string; // Mux playback ID
  uploadId?: string; // Mux upload ID (for polling asset status)
}

const STORE_PATH = path.join(process.cwd(), "data", "videos.json");

export async function listVideos(): Promise<VideoEntry[]> {
  try {
    const raw = await fs.readFile(STORE_PATH, "utf-8");
    return JSON.parse(raw);
  } catch {
    return [];
  }
}

export async function addVideo(entry: VideoEntry): Promise<void> {
  const videos = await listVideos();
  videos.unshift(entry);
  await fs.writeFile(STORE_PATH, JSON.stringify(videos, null, 2));
}
