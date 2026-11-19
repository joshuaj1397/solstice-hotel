import type { NextRequest } from "next/server";
import { relay } from "@/lib/server/agent";
import { staffFrom } from "@/lib/server/session";

export async function GET(req: NextRequest) {
  if (!(await staffFrom(req))) return Response.json({ error: "not_signed_in" }, { status: 401 });
  return relay("/v1/group/inquiries");
}
