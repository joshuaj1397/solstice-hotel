import type { NextRequest } from "next/server";
import { relayStream } from "@/lib/server/agent";

/** Free-text email intake (LLM extraction, then code verification) → full workflow. */
export async function POST(req: NextRequest) {
  const { email } = await req.json();
  if (typeof email !== "string" || email.trim().length < 20 || email.length > 8000) {
    return Response.json({ error: "bad_request", message: "Paste the full inquiry email (20–8000 characters)." }, { status: 400 });
  }
  return relayStream("/v1/group/intake/email", { email });
}
