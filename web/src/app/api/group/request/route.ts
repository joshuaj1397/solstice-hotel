import type { NextRequest } from "next/server";
import { relayStream } from "@/lib/server/agent";

/** Structured web-portal group request → saved inquiry → workflow, streamed. No LLM parsing needed. */
export async function POST(req: NextRequest) {
  const body = await req.json();
  return relayStream("/v1/group/inquiries", body);
}
