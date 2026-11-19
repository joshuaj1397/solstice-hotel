import { NextResponse, type NextRequest } from "next/server";
import { agentFetch, relay } from "@/lib/server/agent";
import { GUEST_COOKIE, cookieOptions, guestFrom, seal } from "@/lib/server/session";

/** Sign in with confirmation number + last name (the same check a front desk does). */
export async function POST(req: NextRequest) {
  const { reservation_id, last_name } = await req.json();
  const res = await agentFetch("/v1/guest/verify", {
    method: "POST",
    body: JSON.stringify({ reservation_id, last_name }),
  }).catch(() => null);
  if (!res) return NextResponse.json({ error: "agent_unavailable" }, { status: 503 });
  if (!res.ok) {
    return NextResponse.json(
      { error: "not_found", message: "We couldn't find a reservation with that confirmation number and last name." },
      { status: 404 },
    );
  }
  const profile = await res.json();
  const out = NextResponse.json(profile);
  out.cookies.set(GUEST_COOKIE, await seal({ guestId: profile.guest.guest_id, firstName: profile.guest.first_name }), cookieOptions);
  return out;
}

export async function GET(req: NextRequest) {
  const s = await guestFrom(req);
  if (!s?.guestId) return NextResponse.json({ signedIn: false }, { status: 401 });
  return relay(`/v1/guest/${encodeURIComponent(s.guestId)}`);
}

export async function DELETE() {
  const out = NextResponse.json({ ok: true });
  out.cookies.delete(GUEST_COOKIE);
  return out;
}
