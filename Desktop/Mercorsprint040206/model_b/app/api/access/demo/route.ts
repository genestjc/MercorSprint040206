import { NextResponse } from "next/server";
import { setMemberSession, clearMemberSession } from "@/lib/session";

export async function POST() {
  if (process.env.NODE_ENV === "production") {
    return NextResponse.json({ error: "Not available" }, { status: 403 });
  }
  await setMemberSession({ demo: true });
  return NextResponse.json({ ok: true });
}

export async function DELETE() {
  clearMemberSession();
  return NextResponse.json({ ok: true });
}
