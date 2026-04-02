"use client";

import { useRouter } from "next/navigation";

export function ResetMembership() {
  const router = useRouter();
  return (
    <button
      className="btn btn-outline"
      style={{ padding: "6px 12px", fontSize: 12 }}
      onClick={async () => {
        await fetch("/api/access/demo", { method: "DELETE" });
        router.refresh();
      }}
    >
      Reset (re-lock)
    </button>
  );
}
