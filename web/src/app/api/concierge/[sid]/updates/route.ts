import type { NextRequest } from "next/server";
import { relay } from "@/lib/server/agent";

/** Staff replies on hand-off cases flow back into the guest's conversation. */
export async function GET(req: NextRequest, ctx: RouteContext<"/api/concierge/[sid]/updates">) {
  const { sid } = await ctx.params;
  const after = Number(req.nextUrl.searchParams.get("after") ?? 0) || 0;
  return relay(`/v1/concierge/sessions/${encodeURIComponent(sid)}/updates?after=${after}`);
}
