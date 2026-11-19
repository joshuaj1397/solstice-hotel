"use client";
/* eslint-disable @typescript-eslint/no-explicit-any */

import { useCallback, useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { Concierge } from "@/components/concierge/Concierge";
import { SignInForm } from "@/components/SignInForm";
import { toast } from "@/components/Toaster";
import { Chip, EmptyState, PlainDate, Spinner, TierBadge, humanize, statusTone } from "@/components/ui";
import { money } from "@/lib/dates";

export function StayCompanion() {
  const router = useRouter();
  const [profile, setProfile] = useState<any>(null);
  const [state, setState] = useState<"loading" | "signed-out" | "ready">("loading");
  const [selected, setSelected] = useState<string | null>(null);
  const [ask, setAsk] = useState<{ text: string; nonce: number } | null>(null);

  const apply = useCallback((p: any | null) => {
    if (!p) return setState("signed-out");
    setProfile(p);
    setState("ready");
    setSelected((cur) => cur ?? pickDefault(p.reservations, p.today));
  }, []);
  const load = useCallback(async () => apply(await fetchProfile()), [apply]);

  useEffect(() => {
    let alive = true;
    fetchProfile().then((p) => alive && apply(p));
    return () => {
      alive = false;
    };
  }, [apply]);

  if (state === "loading") {
    return (
      <div className="flex items-center gap-2 p-10 text-muted">
        <Spinner label="Loading your stay" /> Loading your stay…
      </div>
    );
  }
  if (state === "signed-out") {
    return (
      <div className="mx-auto max-w-md px-4 py-12">
        <h1 className="text-3xl font-semibold">Manage your stay</h1>
        <p className="mb-6 mt-2 text-muted">Sign in with your confirmation number and last name, just like at the front desk.</p>
        <div className="card p-6">
          <SignInForm onSignedIn={load} />
        </div>
      </div>
    );
  }

  const g = profile.guest;
  const res = profile.reservations.find((r: any) => r.reservation_id === selected) ?? profile.reservations[0];
  const signOut = async () => {
    await fetch("/api/session", { method: "DELETE" });
    router.push("/");
    router.refresh();
  };

  return (
    <div className="mx-auto grid max-w-7xl gap-6 px-4 py-6 sm:px-6 lg:grid-cols-12">
      <div className="space-y-4 lg:col-span-5">
        <section className="card p-5" aria-labelledby="welcome">
          <div className="flex items-start gap-3">
            <div>
              <p className="eyebrow">Welcome back</p>
              <h1 id="welcome" className="text-3xl font-semibold">{g.first_name}</h1>
            </div>
            <div className="ms-auto text-end">
              <TierBadge tier={g.loyalty_tier} />
              {g.loyalty_points > 0 && <p className="mt-1 text-xs text-muted">{g.loyalty_points.toLocaleString()} points</p>}
            </div>
          </div>
          <p className="mt-3 rounded-xl bg-sunken p-3 text-sm text-muted">{profile.benefits.summary}</p>
          <button type="button" onClick={signOut} className="mt-3 text-xs font-semibold text-muted underline-offset-2 hover:underline">
            Not {g.first_name}? Sign out
          </button>
        </section>

        {profile.reservations.length > 1 && (
          <fieldset className="card p-4">
            <legend className="sr-only">Choose a stay</legend>
            <p className="eyebrow mb-2">Your stays</p>
            <div className="grid gap-2">
              {profile.reservations.map((r: any) => (
                <label key={r.reservation_id} className="flex cursor-pointer items-center gap-3 rounded-xl border border-line p-3 has-[:checked]:border-sun has-[:checked]:bg-sun-soft/50">
                  <input type="radio" name="stay" value={r.reservation_id} checked={r.reservation_id === res.reservation_id} onChange={() => setSelected(r.reservation_id)} />
                  <span className="min-w-0 flex-1 text-sm">
                    <strong>{r.city}</strong> · <PlainDate iso={r.check_in} year={false} />–<PlainDate iso={r.check_out} />
                  </span>
                  <Chip tone={statusTone(r.status)}>{r.status}</Chip>
                </label>
              ))}
            </div>
          </fieldset>
        )}

        {res && <StayCard res={res} onAsk={(text) => setAsk({ text, nonce: Date.now() })} onChange={load} />}

        <section className="card p-5" aria-labelledby="activity">
          <h2 id="activity" className="text-lg font-semibold">Requests &amp; cases</h2>
          {profile.requests.length === 0 && profile.cases.length === 0 ? (
            <EmptyState title="Nothing open">Requests you make here or with Sol show up instantly.</EmptyState>
          ) : (
            <ul className="mt-2 divide-y divide-line text-sm">
              {profile.cases.map((c: any) => (
                <li key={c.case_id} className="flex items-center gap-2 py-2">
                  <span className="font-mono text-xs">{c.case_id}</span>
                  <span className="flex-1">{humanize(c.category)} → {c.route_to.split(" (")[0]}</span>
                  <Chip tone={statusTone(c.status)}>{humanize(c.status)}</Chip>
                </li>
              ))}
              {profile.requests.map((r: any) => (
                <li key={r.request_id} className="flex items-center gap-2 py-2">
                  <span className="font-mono text-xs">{r.request_id}</span>
                  <span className="flex-1">
                    {humanize(r.kind)} {r.details?.granted_time || r.details?.requested_time ? `· ${r.details.granted_time ?? r.details.requested_time}` : ""}
                  </span>
                  <Chip tone={statusTone(r.status)}>{r.status === "pending_desk" ? "With front desk" : humanize(r.status)}</Chip>
                </li>
              ))}
            </ul>
          )}
        </section>
      </div>

      <div className="lg:col-span-7 lg:sticky lg:top-20 lg:self-start">
        <Concierge
          greeting={`Hi ${g.first_name}! I'm Sol, your Solstice concierge. I can see your ${profile.reservations.length > 1 ? "stays" : "stay"}${res ? ` at ${res.property_name}` : ""}. Ask me anything, from policies to late check-out to booking your next trip.`}
          prompts={["Can I get a late checkout?", "What are my loyalty perks?", "Can I bring my dog?", "I'd like to talk to a person"]}
          onChange={load}
          externalAsk={ask}
        />
      </div>
    </div>
  );
}

async function fetchProfile(): Promise<any | null> {
  const r = await fetch("/api/session").catch(() => null);
  return r && r.ok ? r.json() : null;
}

function pickDefault(rs: any[], today: string): string | null {
  const inhouse = rs.find((r) => r.status === "Checked-in");
  if (inhouse) return inhouse.reservation_id;
  const next = rs.filter((r) => r.status === "Confirmed" && r.check_in >= today).sort((a, b) => (a.check_in < b.check_in ? -1 : 1))[0];
  return (next ?? rs[rs.length - 1])?.reservation_id ?? null;
}

const TIMES = ["12:00 PM", "1:00 PM", "2:00 PM", "3:00 PM"];
const EARLY = ["8:00 AM", "10:00 AM", "12:00 PM", "1:00 PM"];

function StayCard({ res, onAsk, onChange }: { res: any; onAsk: (t: string) => void; onChange: () => void }) {
  const [busy, setBusy] = useState<string | null>(null);
  const late = useRef<HTMLSelectElement>(null);
  const early = useRef<HTMLSelectElement>(null);
  const active = res.status === "Confirmed" || res.status === "Checked-in";

  const request = async (kind: string, time?: string) => {
    setBusy(kind);
    const r = await fetch("/api/actions/request", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ kind, time, reservation_id: res.reservation_id }),
    });
    const j = await r.json();
    setBusy(null);
    if (!r.ok) return toast(j.message ?? "Couldn't log that request.", "bad");
    toast(j.status === "confirmed" ? `Confirmed: ${humanize(kind)}${j.granted_time ? ` at ${j.granted_time}` : ""}` : `${humanize(kind)} sent to the front desk`, j.status === "confirmed" ? "ok" : "info");
    onChange();
  };

  return (
    <section className="card overflow-hidden" aria-labelledby="stay-title">
      <div className="bg-gradient-to-br from-dusk to-[color-mix(in_oklab,var(--color-dusk)_70%,var(--color-sun))] p-5 text-on-accent">
        <p className="text-xs font-semibold uppercase tracking-widest opacity-80">{res.reservation_id} · {res.status}</p>
        <h2 id="stay-title" className="mt-1 text-2xl font-semibold">{res.property_name}</h2>
        <p className="mt-1 text-sm opacity-90">
          <PlainDate iso={res.check_in} weekday year={false} /> → <PlainDate iso={res.check_out} weekday /> · {res.total_nights} night{res.total_nights === 1 ? "" : "s"}
        </p>
      </div>
      <dl className="grid grid-cols-2 gap-x-4 gap-y-2 p-5 text-sm">
        <div><dt className="text-muted">Room</dt><dd className="font-medium">{res.room_type}</dd></div>
        <div><dt className="text-muted">Rate</dt><dd className="font-medium">{res.rate_plan}</dd></div>
        <div><dt className="text-muted">Nightly</dt><dd className="font-medium">{res.nightly_rate > 0 ? money(res.nightly_rate) : "Points stay"}</dd></div>
        <div><dt className="text-muted">Payment</dt><dd className="font-medium">{res.card_on_file ? "Card on file" : "At check-in"}</dd></div>
        {res.special_requests && (
          <div className="col-span-2"><dt className="text-muted">Your requests</dt><dd>{res.special_requests}</dd></div>
        )}
      </dl>
      {active ? (
        <div className="space-y-3 border-t border-line p-5">
          <p className="eyebrow">One-tap requests</p>
          <div className="flex flex-wrap items-end gap-2">
            <div>
              <label className="label" htmlFor="late-time">Late check-out</label>
              <select id="late-time" ref={late} className="input !w-auto" defaultValue="1:00 PM">
                {TIMES.map((t) => <option key={t}>{t}</option>)}
              </select>
            </div>
            <button type="button" className="btn btn-primary" disabled={!!busy} onClick={() => request("late_checkout", late.current?.value)}>
              {busy === "late_checkout" ? <Spinner label="Requesting" /> : "Request"}
            </button>
          </div>
          <div className="flex flex-wrap items-end gap-2">
            <div>
              <label className="label" htmlFor="early-time">Early check-in</label>
              <select id="early-time" ref={early} className="input !w-auto" defaultValue="12:00 PM">
                {EARLY.map((t) => <option key={t}>{t}</option>)}
              </select>
            </div>
            <button type="button" className="btn btn-ghost" disabled={!!busy} onClick={() => request("early_checkin", early.current?.value)}>
              {busy === "early_checkin" ? <Spinner label="Requesting" /> : "Request"}
            </button>
          </div>
          <div className="flex flex-wrap gap-2 pt-1">
            <button type="button" className="btn btn-ghost" disabled={!!busy} onClick={() => request("upgrade")}>Request upgrade</button>
            <button type="button" className="btn btn-ghost" onClick={() => onAsk("What would it cost to cancel this reservation?")}>Cancellation options</button>
            <button type="button" className="btn btn-ghost" onClick={() => onAsk("I'd like to talk to a person")}>Talk to a person</button>
          </div>
        </div>
      ) : (
        <p className="border-t border-line p-5 text-sm text-muted">This stay is {res.status.toLowerCase()}. Questions about it? Ask Sol, who can open a case with the full history.</p>
      )}
    </section>
  );
}
