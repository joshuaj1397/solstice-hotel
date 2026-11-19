import { NextResponse, type NextRequest } from "next/server";
import { STAFF_COOKIE, cookieOptions, seal, staffFrom } from "@/lib/server/session";
import { secrets } from "@/lib/server/vault";

/** PoC staff sign-in (shared passcode from Vault). Production: SSO via the hotel's IdP (Entra/Okta). */
export async function POST(req: NextRequest) {
  const { passcode, name } = await req.json();
  if (passcode !== (await secrets()).staffPasscode) {
    return NextResponse.json({ error: "denied", message: "Incorrect passcode." }, { status: 401 });
  }
  const out = NextResponse.json({ ok: true });
  out.cookies.set(STAFF_COOKIE, await seal({ staff: String(name || "Front Desk").slice(0, 40) }, 12), cookieOptions);
  return out;
}

export async function GET(req: NextRequest) {
  const s = await staffFrom(req);
  return s ? NextResponse.json(s) : NextResponse.json({ error: "not_signed_in" }, { status: 401 });
}

export async function DELETE() {
  const out = NextResponse.json({ ok: true });
  out.cookies.delete(STAFF_COOKIE);
  return out;
}
