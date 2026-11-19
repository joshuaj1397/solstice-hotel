import type { NextRequest } from "next/server";
import { relayStream } from "@/lib/server/agent";
import { staffFrom } from "@/lib/server/session";

/** Group sales runs the workflow on a portal inquiry; progress streams back step by step. */
export async function POST(req: NextRequest, ctx: RouteContext<"/api/group/inquiries/[id]/run">) {
  if (!(await staffFrom(req))) return Response.json({ error: "not_signed_in" }, { status: 401 });
  const { id } = await ctx.params;
  return relayStream(`/v1/group/inquiries/${encodeURIComponent(id)}/run`, {});
}
