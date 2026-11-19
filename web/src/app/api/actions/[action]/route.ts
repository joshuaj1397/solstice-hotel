import type { NextRequest } from "next/server";
import { relay } from "@/lib/server/agent";
import { guestFrom } from "@/lib/server/session";

/**
 * Deterministic one-tap actions. These call the same domain services as the agent's tools,
 * without the model, so they keep working if the LLM is degraded.
 */
const ROUTES: Record<string, string> = { request: "/v1/actions/request", cancel: "/v1/actions/cancel", escalate: "/v1/actions/escalate" };

export async function POST(req: NextRequest, ctx: RouteContext<"/api/actions/[action]">) {
  const { action } = await ctx.params;
  const path = ROUTES[action];
  if (!path) return Response.json({ error: "unknown_action" }, { status: 404 });
  const s = await guestFrom(req);
  const body = await req.json();
  if (action !== "escalate" && !s?.guestId) {
    return Response.json({ error: "not_signed_in", message: "Please sign in to manage your stay." }, { status: 401 });
  }
  return relay(path, { method: "POST", body: JSON.stringify({ ...body, guest_id: s?.guestId ?? null }) });
}
