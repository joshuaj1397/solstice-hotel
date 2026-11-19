import type { NextRequest } from "next/server";
import { relayStream } from "@/lib/server/agent";
import { guestFrom } from "@/lib/server/session";

export async function POST(req: NextRequest, ctx: RouteContext<"/api/concierge/[sid]/messages">) {
  const { sid } = await ctx.params;
  const { text } = await req.json();
  const s = await guestFrom(req);
  if (typeof text !== "string" || !text.trim() || text.length > 2000) {
    return Response.json({ error: "bad_request", message: "Message must be 1–2000 characters." }, { status: 400 });
  }
  return relayStream(`/v1/concierge/sessions/${encodeURIComponent(sid)}/messages`, {
    text,
    guest_id: s?.guestId ?? null,
  });
}
