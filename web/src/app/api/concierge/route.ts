import type { NextRequest } from "next/server";
import { relay } from "@/lib/server/agent";
import { guestFrom } from "@/lib/server/session";

/** Start a concierge conversation, bound to the signed-in guest if there is one. */
export async function POST(req: NextRequest) {
  const s = await guestFrom(req);
  return relay("/v1/concierge/sessions", { method: "POST", body: JSON.stringify({ guest_id: s?.guestId ?? null }) });
}
