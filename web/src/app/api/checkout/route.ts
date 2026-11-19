import type { NextRequest } from "next/server";
import { relay } from "@/lib/server/agent";
import { guestFrom } from "@/lib/server/session";

/**
 * Secure checkout. In production the card fields are a payment provider's hosted iframe and
 * the PAN never reaches Solstice servers at all (PCI SAQ-A). In this PoC the BFF plays the
 * tokenizer: it validates the card, keeps ONLY the last four digits, and discards the rest.
 * Neither the agent service, the database, nor the LLM ever sees a full card number.
 */
function luhn(digits: string): boolean {
  let sum = 0;
  let alt = false;
  for (let i = digits.length - 1; i >= 0; i--) {
    let d = Number(digits[i]);
    if (alt) d = d * 2 > 9 ? d * 2 - 9 : d * 2;
    sum += d;
    alt = !alt;
  }
  return sum % 10 === 0;
}

export async function POST(req: NextRequest) {
  const s = await guestFrom(req);
  const { hold_id, name, email, cc_number, cc_exp, session_id } = await req.json();
  const digits = String(cc_number ?? "").replace(/\D/g, "");
  if (digits.length < 13 || digits.length > 19 || !luhn(digits)) {
    return Response.json({ error: "card_invalid", message: "That card number doesn't look right." }, { status: 422 });
  }
  if (!/^(0[1-9]|1[0-2])\/\d{2}$/.test(String(cc_exp ?? ""))) {
    return Response.json({ error: "exp_invalid", message: "Use MM/YY for the expiry date." }, { status: 422 });
  }
  const full = String(name ?? "").trim().replace(/\s+/g, " ");
  const cut = full.lastIndexOf(" ");
  const first = cut > 0 ? full.slice(0, cut) : full;
  const last = cut > 0 ? full.slice(cut + 1) : full;
  return relay("/v1/bookings", {
    method: "POST",
    body: JSON.stringify({
      hold_id, first_name: first, last_name: last, email, card_last4: digits.slice(-4),
      guest_id: s?.guestId ?? null, session_id: session_id ?? null,
    }),
  });
}
