import type { NextRequest } from "next/server";
import { relay } from "@/lib/server/agent";
import { staffFrom } from "@/lib/server/session";

/** Staff console proxy → agent service /v1/staff/*. Requires the staff cookie. */
async function forward(req: NextRequest, path: string[], method: "GET" | "POST") {
  const s = await staffFrom(req);
  if (!s) return Response.json({ error: "not_signed_in" }, { status: 401 });
  if (path.some((p) => p === ".." || p.includes("/"))) return Response.json({ error: "bad_path" }, { status: 400 });
  const qs = req.nextUrl.search;
  const target = `/v1/staff/${path.map(encodeURIComponent).join("/")}${qs}`;
  if (method === "GET") return relay(target);
  const body = await req.json().catch(() => ({}));
  // Attribute every staff action to the signed-in staff member, not to whatever the client sent.
  return relay(target, { method: "POST", body: JSON.stringify({ ...body, author_name: s.staff, staff: s.staff, reviewer: s.staff }) });
}

export async function GET(req: NextRequest, ctx: RouteContext<"/api/staff/[...path]">) {
  return forward(req, (await ctx.params).path, "GET");
}

export async function POST(req: NextRequest, ctx: RouteContext<"/api/staff/[...path]">) {
  return forward(req, (await ctx.params).path, "POST");
}
