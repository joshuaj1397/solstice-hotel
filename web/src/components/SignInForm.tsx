"use client";

import { useRouter } from "next/navigation";
import { useRef, useState, type FormEvent } from "react";
import { Spinner } from "./ui";

const DEMO_GUESTS = [
  ["R55004", "Chen", "Platinum · Denver · suite upgrade ask"],
  ["R55023", "Moreau", "No tier · Chicago · 1 PM checkout ask"],
  ["R55006", "Webb", "Gold · in-house · minibar dispute"],
  ["R55012", "Kalinski", "Checked out · late refund request"],
  ["R55009", "Smith", "Advance Purchase · wants to cancel"],
  ["R55013", "Brandt", "Platinum VIP · Chicago suite"],
  ["R55008", "Nguyen", "Expired promo code"],
] as const;

export function SignInForm({ compact = false, onSignedIn }: { compact?: boolean; onSignedIn?: () => void }) {
  const router = useRouter();
  const form = useRef<HTMLFormElement>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const submit = async (e: FormEvent<HTMLFormElement>) => {
    e.preventDefault();
    setBusy(true);
    setError(null);
    const f = new FormData(e.currentTarget);
    const r = await fetch("/api/session", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ reservation_id: f.get("reservation_id"), last_name: f.get("last_name") }),
    });
    setBusy(false);
    if (!r.ok) {
      setError((await r.json().catch(() => ({}))).message ?? "Something went wrong.");
      return;
    }
    if (onSignedIn) onSignedIn(); // already on /stay: reload in place
    else router.push("/stay");
  };

  const fill = (res: string, last: string) => {
    const el = form.current;
    if (!el) return;
    (el.elements.namedItem("reservation_id") as HTMLInputElement).value = res;
    (el.elements.namedItem("last_name") as HTMLInputElement).value = last;
    el.requestSubmit();
  };

  return (
    <div className="space-y-4">
      <form ref={form} onSubmit={submit} className="space-y-3" aria-describedby={error ? "signin-error" : undefined}>
        <div>
          <label className="label" htmlFor="reservation_id">Confirmation number</label>
          <input
            id="reservation_id" name="reservation_id" className="input font-mono uppercase" required
            autoComplete="off" autoCapitalize="characters" spellCheck={false} pattern="[Rr]\d{5}" placeholder="R55001"
            enterKeyHint="next"
          />
          <p className="field-error mt-1 text-xs text-bad">Confirmation numbers look like R55001.</p>
        </div>
        <div>
          <label className="label" htmlFor="last_name">Last name</label>
          <input id="last_name" name="last_name" className="input" required autoComplete="family-name" spellCheck={false} enterKeyHint="go" />
        </div>
        {error && (
          <p id="signin-error" role="alert" className="rounded-lg bg-bad-soft p-2 text-sm text-bad">{error}</p>
        )}
        <button type="submit" className="btn btn-primary w-full" disabled={busy}>
          {busy ? <Spinner label="Finding your stay" /> : "Find my stay"}
        </button>
      </form>
      {!compact && (
        <details className="rounded-xl border border-line bg-sunken/60 p-3 text-sm">
          <summary className="cursor-pointer font-semibold">Demo guests from the sample data</summary>
          <ul className="mt-2 space-y-1">
            {DEMO_GUESTS.map(([res, last, note]) => (
              <li key={res}>
                <button type="button" onClick={() => fill(res, last)} className="w-full rounded-lg px-2 py-1.5 text-start hover:bg-surface">
                  <span className="font-mono text-xs">{res}</span> · <strong>{last}</strong>
                  <span className="block text-xs text-muted">{note}</span>
                </button>
              </li>
            ))}
          </ul>
        </details>
      )}
    </div>
  );
}
