import type { NextRequest } from "next/server";
import { relay } from "@/lib/server/agent";

export async function GET(_req: NextRequest, ctx: RouteContext<"/api/group/proposals/[id]">) {
  const { id } = await ctx.params;
  return relay(`/v1/group/proposals/${encodeURIComponent(id)}`);
}
