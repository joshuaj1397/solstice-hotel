import type { NextRequest } from "next/server";
import { relay } from "@/lib/server/agent";
import { guestFrom } from "@/lib/server/session";

export async function POST(req: NextRequest) {
  const s = await guestFrom(req);
  const body = await req.json();
  return relay("/v1/holds", { method: "POST", body: JSON.stringify({ ...body, guest_id: s?.guestId ?? null }) });
}
