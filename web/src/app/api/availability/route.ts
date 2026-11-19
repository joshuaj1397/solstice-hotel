import type { NextRequest } from "next/server";
import { relay } from "@/lib/server/agent";

export async function GET(req: NextRequest) {
  const q = new URLSearchParams();
  for (const k of ["where", "check_in", "check_out", "room_type", "session_id"]) {
    const v = req.nextUrl.searchParams.get(k);
    if (v) q.set(k, v);
  }
  return relay(`/v1/availability?${q}`);
}
