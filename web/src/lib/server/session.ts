import "server-only";
import { SignJWT, jwtVerify } from "jose";
import type { NextRequest } from "next/server";
import { secrets } from "./vault";

/**
 * Signed, httpOnly cookie sessions. The browser never sees a guest_id it could tamper
 * with: the BFF derives identity from this cookie and passes it to the agent service.
 */
export const GUEST_COOKIE = "sol_guest";
export const STAFF_COOKIE = "sol_staff";

export type GuestSession = { guestId?: string; firstName?: string; conciergeSessionId?: string };
export type StaffSession = { staff: string };

async function key() {
  return new TextEncoder().encode((await secrets()).sessionSecret);
}

export async function seal(payload: Record<string, unknown>, hours = 8): Promise<string> {
  return new SignJWT(payload)
    .setProtectedHeader({ alg: "HS256" })
    .setIssuedAt()
    .setExpirationTime(`${hours}h`)
    .sign(await key());
}

export async function unseal<T>(token: string | undefined): Promise<T | null> {
  if (!token) return null;
  try {
    const { payload } = await jwtVerify(token, await key());
    return payload as T;
  } catch {
    return null;
  }
}

export const guestFrom = (req: NextRequest) => unseal<GuestSession>(req.cookies.get(GUEST_COOKIE)?.value);
export const staffFrom = (req: NextRequest) => unseal<StaffSession>(req.cookies.get(STAFF_COOKIE)?.value);

export const cookieOptions = {
  httpOnly: true,
  sameSite: "lax" as const,
  secure: process.env.NODE_ENV === "production" && process.env.INSECURE_COOKIES !== "1",
  path: "/",
};
