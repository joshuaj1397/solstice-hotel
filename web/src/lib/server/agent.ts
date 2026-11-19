import "server-only";
import { secrets } from "./vault";

/** Server-to-server client for the Python ADK agent service. Never exposed to the browser. */
const AGENT_URL = process.env.AGENT_URL ?? "http://localhost:8080";

async function headers(extra?: HeadersInit): Promise<Headers> {
  const h = new Headers(extra);
  const token = (await secrets()).serviceToken;
  if (token) h.set("x-service-token", token);
  return h;
}

export async function agentFetch(path: string, init: RequestInit = {}): Promise<Response> {
  const h = await headers(init.headers);
  if (init.body && !h.has("content-type")) h.set("content-type", "application/json");
  return fetch(`${AGENT_URL}${path}`, { ...init, headers: h, cache: "no-store" });
}

/** JSON passthrough that preserves the upstream status code. */
export async function relay(path: string, init: RequestInit = {}): Promise<Response> {
  try {
    const res = await agentFetch(path, init);
    const body = await res.text();
    return new Response(body || "{}", { status: res.status, headers: { "content-type": "application/json" } });
  } catch {
    return Response.json(
      { error: "agent_unavailable", message: "The concierge service is unreachable. Please try again shortly." },
      { status: 503 },
    );
  }
}

/** Server-Sent Events passthrough: the browser reads the agent's stream through the BFF. */
export async function relayStream(path: string, body: unknown): Promise<Response> {
  try {
    const res = await agentFetch(path, { method: "POST", body: JSON.stringify(body) });
    if (!res.ok || !res.body) return relay(path, { method: "POST", body: JSON.stringify(body) });
    return new Response(res.body, {
      headers: { "content-type": "text/event-stream", "cache-control": "no-cache, no-transform", "x-accel-buffering": "no" },
    });
  } catch {
    return Response.json({ error: "agent_unavailable", message: "The concierge service is unreachable." }, { status: 503 });
  }
}
