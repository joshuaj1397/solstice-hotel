"use client";
/* eslint-disable @typescript-eslint/no-explicit-any */

import { useEffect, useRef, useState, type FormEvent, type ReactNode } from "react";
import { money } from "@/lib/dates";
import { toast } from "@/components/Toaster";
import { Chip, PlainDate, Spinner, humanize, statusTone } from "@/components/ui";

type CardProps = { kind: string; data: any; onAsk: (s: string) => void; onChange?: () => void; sessionId: string | null; internals: boolean };

function Shell({ eyebrow, title, tone, children, aside }: { eyebrow: string; title: ReactNode; tone?: string; children?: ReactNode; aside?: ReactNode }) {
  return (
    <article className="rise max-w-[92%] rounded-2xl border border-line bg-surface p-4 shadow-sm">
      <div className="flex items-start gap-3">
        <div className="min-w-0 flex-1">
          <p className="eyebrow">{eyebrow}</p>
          <h3 className="mt-0.5 font-sans text-base font-semibold">{title}</h3>
        </div>
        {aside}
      </div>
      {children && <div className="mt-2 space-y-2 text-sm">{children}</div>}
      {tone && <span className="sr-only">{tone}</span>}
    </article>
  );
}

function PolicyRefs({ refs }: { refs?: number[] }) {
  if (!refs?.length) return null;
  return (
    <p className="flex flex-wrap gap-1">
      {refs.map((r) => (
        <Chip key={r} tone="dusk">Policy {r}</Chip>
      ))}
    </p>
  );
}

export function CardView(p: CardProps) {
  const d = p.data ?? {};
  if (d.error) {
    return (
      <Shell eyebrow="Heads up" title={humanize(d.error)}>
        <p className="text-muted">{d.message}</p>
      </Shell>
    );
  }
  switch (p.kind) {
    case "request_stay_change":
      return <RequestCard d={d} />;
    case "check_availability":
      return <AvailabilityCard d={d} {...p} />;
    case "hold_room":
      return <HoldCard hold={d} sessionId={p.sessionId} onChange={p.onChange} />;
    case "cancellation_options":
      return <CancelCard d={d} onAsk={p.onAsk} onChange={p.onChange} />;
    case "report_problem":
      return <CaseCard c={d.case} assessment={d.assessment_for_guest} />;
    case "escalate_to_staff":
      return <CaseCard c={d} />;
    case "lookup_policy":
      return <PolicyCard d={d} />;
    case "property_info":
      return d.found ? <PropertyCard d={d} /> : null;
    case "get_my_stay":
    case "find_reservation":
      return p.internals ? (
        <Shell eyebrow="Looked up" title="Your stays on file">
          <p className="text-muted">{(d.stays ?? []).map((s: any) => `${s.reservation_id} · ${s.property_name}`).join(" · ")}</p>
        </Shell>
      ) : null;
    default:
      return null;
  }
}

function RequestCard({ d }: { d: any }) {
  const label = { late_checkout: "Late check-out", early_checkin: "Early check-in", upgrade: "Room upgrade", amenity: "Special request" }[d.kind as string] ?? "Request";
  const confirmed = d.status === "confirmed";
  return (
    <Shell
      eyebrow={`${label} · ${d.property_name ?? ""}`}
      title={confirmed ? `Confirmed${d.granted_time ? ` · ${d.granted_time}` : ""}` : d.status === "not_needed" ? "No request needed" : "Sent to the front desk"}
      aside={<Chip tone={statusTone(d.status)}>{confirmed ? "✓ Confirmed" : humanize(d.status)}</Chip>}
    >
      <p className="text-muted">{d.explanation}</p>
      <div className="flex flex-wrap items-center gap-2">
        <PolicyRefs refs={d.policy_refs} />
        {d.request_id && <span className="font-mono text-xs text-muted">{d.request_id}</span>}
      </div>
    </Shell>
  );
}

function AvailabilityCard({ d, onChange, sessionId }: { d: any } & CardProps) {
  const [hold, setHold] = useState<any>(null);
  const [pending, setPending] = useState<string | null>(null);
  const place = async (property_code: string, room_type: string, check_in: string, check_out: string) => {
    setPending(`${property_code}${room_type}${check_in}`);
    const r = await fetch("/api/holds", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ property_code, room_type, check_in, check_out, session_id: sessionId }),
    });
    const j = await r.json();
    setPending(null);
    if (!r.ok) return toast(j.message ?? "That room is no longer available.", "warn");
    setHold(j);
    onChange?.();
  };
  if (hold) return <HoldCard hold={hold} sessionId={sessionId} onChange={onChange} />;
  if (!d.found && !d.alternatives?.length) {
    return (
      <Shell eyebrow="Availability" title="No match">
        <p className="text-muted">{d.message}</p>
      </Shell>
    );
  }
  return (
    <Shell
      eyebrow={`${d.property_name ?? "Availability"} · ${d.nights ?? ""} night${d.nights === 1 ? "" : "s"}`}
      title={
        <>
          <PlainDate iso={d.check_in} year={false} /> → <PlainDate iso={d.check_out} />
        </>
      }
      aside={<Chip tone="ok">Live</Chip>}
    >
      {d.options?.length ? (
        <ul className="divide-y divide-line">
          {d.options.map((o: any) => (
            <li key={o.room_type} className="flex items-center gap-3 py-2">
              <div className="min-w-0 flex-1">
                <p className="font-medium">{o.room_type}</p>
                <p className="text-xs text-muted">
                  {money(o.nightly_rate)} / night · {money(o.total_before_tax)} before tax · {o.available} left
                </p>
              </div>
              <button type="button" className="btn btn-primary !py-1.5" disabled={!!pending} onClick={() => place(d.property_code, o.room_type, d.check_in, d.check_out)}>
                {pending === `${d.property_code}${o.room_type}${d.check_in}` ? <Spinner label="Holding" /> : "Hold 15 min"}
              </button>
            </li>
          ))}
        </ul>
      ) : (
        <p className="text-muted">Nothing left for those dates, but here are the closest options:</p>
      )}
      {d.alternatives?.length > 0 && (
        <ul className="space-y-1">
          {d.alternatives.map((a: any, i: number) => (
            <li key={i} className="flex items-center gap-2 rounded-xl bg-sun-soft/60 px-3 py-2">
              <span className="flex-1 text-xs">
                <strong>{a.property_name}</strong> · <PlainDate iso={a.check_in} year={false} />→<PlainDate iso={a.check_out} year={false} /> · {a.room_type} · {money(a.nightly_rate)}
                {a.distance_miles ? ` · ${a.distance_miles} mi` : ""}
              </span>
              <button type="button" className="btn btn-ghost !py-1 !text-xs" onClick={() => place(a.property_code, a.room_type, a.check_in, a.check_out)}>
                Hold
              </button>
            </li>
          ))}
        </ul>
      )}
      <p className="text-xs text-muted">Best Available Rate · {d.cancellation}</p>
    </Shell>
  );
}

function useCountdown(iso?: string) {
  const [left, setLeft] = useState<number | null>(null);
  useEffect(() => {
    if (!iso) return;
    const end = Date.parse(iso);
    const tick = () => setLeft(Math.max(0, Math.round((end - Date.now()) / 1000)));
    tick();
    const t = setInterval(tick, 1000);
    return () => clearInterval(t);
  }, [iso]);
  return left;
}

export function HoldCard({ hold, sessionId, onChange }: { hold: any; sessionId: string | null; onChange?: () => void }) {
  const left = useCountdown(hold.expires_at);
  const [booked, setBooked] = useState<any>(null);
  const dialog = useRef<HTMLDialogElement>(null);
  if (booked) {
    return (
      <Shell eyebrow="Booking confirmed" title={`Confirmation ${booked.reservation_id}`} aside={<Chip tone="ok">✓ Booked</Chip>}>
        <p className="text-muted">
          {hold.room_type} at {hold.property_name}, <PlainDate iso={booked.check_in} year={false} /> → <PlainDate iso={booked.check_out} />. Total {money(booked.total_before_tax)} before tax.
        </p>
      </Shell>
    );
  }
  const expired = left === 0;
  return (
    <Shell
      eyebrow={`Room on hold · ${hold.property_name}`}
      title={`${hold.room_type} · ${money(hold.total_before_tax)}`}
      aside={<Chip tone={expired ? "bad" : "sun"}>{expired ? "Expired" : left != null ? `${Math.floor(left / 60)}:${String(left % 60).padStart(2, "0")} left` : "Held"}</Chip>}
    >
      <p className="text-muted">
        <PlainDate iso={hold.check_in} year={false} /> → <PlainDate iso={hold.check_out} /> · {hold.nights} night{hold.nights === 1 ? "" : "s"} at {money(hold.nightly_rate)} · {hold.rate_plan}
      </p>
      <button type="button" className="btn btn-primary" disabled={expired} onClick={() => dialog.current?.showModal()}>
        Complete booking securely
      </button>
      <CheckoutDialog ref={dialog} hold={hold} sessionId={sessionId} onBooked={(b) => { setBooked(b); onChange?.(); }} />
    </Shell>
  );
}

function CheckoutDialog({ ref, hold, sessionId, onBooked }: { ref: React.RefObject<HTMLDialogElement | null>; hold: any; sessionId: string | null; onBooked: (b: any) => void }) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    // modern-web-guidance (light-dismiss-a-dialog): fallback where `closedby` is unsupported
    const dlg = ref.current;
    if (!dlg || "closedBy" in HTMLDialogElement.prototype) return;
    const onClick = (e: MouseEvent) => {
      if (e.target !== dlg) return;
      const r = dlg.getBoundingClientRect();
      if (e.clientY < r.top || e.clientY > r.bottom || e.clientX < r.left || e.clientX > r.right) dlg.close();
    };
    dlg.addEventListener("click", onClick);
    return () => dlg.removeEventListener("click", onClick);
  }, [ref]);

  const submit = async (e: FormEvent<HTMLFormElement>) => {
    e.preventDefault();
    setBusy(true);
    setError(null);
    const f = new FormData(e.currentTarget);
    const r = await fetch("/api/checkout", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ hold_id: hold.hold_id, session_id: sessionId, ...Object.fromEntries(f) }),
    });
    const j = await r.json();
    setBusy(false);
    if (!r.ok) return setError(j.message ?? "We couldn't complete the booking.");
    ref.current?.close();
    toast(`Booked! Confirmation ${j.reservation_id}`, "ok");
    onBooked(j);
  };

  return (
    <dialog ref={ref} className="sheet" {...({ closedby: "any" } as Record<string, string>)} aria-labelledby={`co-${hold.hold_id}`}>
      <form onSubmit={submit} className="space-y-4 p-6">
        <div className="flex items-start">
          <div>
            <p className="eyebrow">Secure checkout</p>
            <h2 id={`co-${hold.hold_id}`} className="text-2xl font-semibold">Confirm your stay</h2>
          </div>
          <button type="button" className="btn btn-ghost ms-auto !px-3 !py-1" onClick={() => ref.current?.close()}>
            Close
          </button>
        </div>
        <p className="rounded-xl bg-sunken p-3 text-sm">
          {hold.room_type} · {hold.property_name}
          <br />
          <PlainDate iso={hold.check_in} /> → <PlainDate iso={hold.check_out} /> · <strong>{money(hold.total_before_tax)}</strong> before tax
        </p>
        <div className="grid gap-3 sm:grid-cols-2">
          <div className="sm:col-span-2">
            <label className="label" htmlFor="co-name">Full name</label>
            <input id="co-name" name="name" className="input" autoComplete="name" required enterKeyHint="next" />
          </div>
          <div className="sm:col-span-2">
            <label className="label" htmlFor="co-email">Email for your confirmation</label>
            <input id="co-email" name="email" type="email" className="input" autoComplete="email" spellCheck={false} required enterKeyHint="next" />
            <p className="field-error mt-1 text-xs text-bad">Enter an email like you@example.com.</p>
          </div>
          <div className="sm:col-span-2">
            <label className="label" htmlFor="co-cc">Card number</label>
            <input id="co-cc" name="cc_number" className="input font-mono" type="text" inputMode="numeric" autoComplete="cc-number" maxLength={23} pattern="[\d ]{13,23}" required enterKeyHint="next" />
            <p className="field-error mt-1 text-xs text-bad">Enter the 13–19 digit number on your card.</p>
          </div>
          <div>
            <label className="label" htmlFor="co-exp">Expiry</label>
            <span id="co-exp-hint" className="mb-1 block text-xs text-muted">Format: MM/YY</span>
            <input id="co-exp" name="cc_exp" className="input font-mono" type="text" autoComplete="cc-exp" aria-describedby="co-exp-hint" maxLength={5} pattern="(0[1-9]|1[0-2])/\d{2}" required enterKeyHint="next" />
          </div>
          <div>
            <label className="label" htmlFor="co-csc">Security code</label>
            <span className="mb-1 block text-xs text-muted">3 or 4 digits</span>
            <input id="co-csc" name="cc_csc" className="input font-mono" type="text" inputMode="numeric" autoComplete="cc-csc" maxLength={4} pattern="[0-9]{3,4}" required enterKeyHint="done" />
          </div>
        </div>
        {error && <p role="alert" className="rounded-lg bg-bad-soft p-2 text-sm text-bad">{error}</p>}
        <p className="text-xs text-muted">
          Demo: use 4242 4242 4242 4242. Only the last four digits are kept. In production this form is the payment provider&apos;s hosted field, so card data never touches Solstice systems.
        </p>
        <button type="submit" className="btn btn-primary w-full" disabled={busy}>
          {busy ? <Spinner label="Confirming" /> : `Confirm booking · ${money(hold.total_before_tax)}`}
        </button>
      </form>
    </dialog>
  );
}

function CancelCard({ d, onAsk, onChange }: { d: any; onAsk: (s: string) => void; onChange?: () => void }) {
  const dlg = useRef<HTMLDialogElement>(null);
  const [done, setDone] = useState(false);
  const [busy, setBusy] = useState(false);
  const confirm = async () => {
    setBusy(true);
    const r = await fetch("/api/actions/cancel", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ reservation_id: d.reservation_id, confirm: true }),
    });
    const j = await r.json();
    setBusy(false);
    dlg.current?.close();
    if (!r.ok) return toast(j.message ?? "Couldn't cancel.", "bad");
    setDone(true);
    toast(`Reservation ${d.reservation_id} cancelled`, "ok");
    onChange?.();
  };
  const tone = d.free_cancellation ? "ok" : d.requires_human ? "dusk" : "warn";
  return (
    <Shell
      eyebrow={`Cancellation terms · ${d.reservation_id}`}
      title={done ? "Cancelled" : d.free_cancellation ? "Free to cancel" : d.requires_human ? "Needs a team member" : d.penalty?.non_refundable ? "Non-refundable rate" : "Cancellation fee applies"}
      aside={<Chip tone={tone}>{d.rate_plan}</Chip>}
    >
      <p className="text-muted">{d.explanation}</p>
      <PolicyRefs refs={d.policy_refs} />
      {!done && d.cancellable && (
        <div className="flex flex-wrap gap-2">
          {d.retention_offer && (
            <button type="button" className="btn btn-ghost" onClick={() => onAsk("Could I change my dates instead of cancelling?")}>
              Change dates instead
            </button>
          )}
          <button type="button" className="btn btn-ghost !text-bad" onClick={() => dlg.current?.showModal()}>
            Cancel reservation…
          </button>
        </div>
      )}
      <dialog ref={dlg} className="sheet" {...({ closedby: "any" } as Record<string, string>)} aria-labelledby={`cx-${d.reservation_id}`}>
        <div className="space-y-4 p-6">
          <h2 id={`cx-${d.reservation_id}`} className="text-xl font-semibold">Cancel {d.reservation_id}?</h2>
          <p className="text-sm text-muted">{d.explanation}</p>
          <div className="flex justify-end gap-2">
            <button type="button" className="btn btn-ghost" onClick={() => dlg.current?.close()} autoFocus>
              Keep my reservation
            </button>
            <button type="button" className="btn btn-dusk" onClick={confirm} disabled={busy}>
              {busy ? <Spinner label="Cancelling" /> : "Yes, cancel"}
            </button>
          </div>
        </div>
      </dialog>
    </Shell>
  );
}

function CaseCard({ c, assessment }: { c: any; assessment?: any }) {
  if (!c) return null;
  return (
    <Shell eyebrow={`Handed to ${c.route_to?.split(" (")[0]}`} title={`Case ${c.case_id}`} aside={<Chip tone={statusTone(c.severity)}>{humanize(c.severity)}</Chip>}>
      {assessment?.assessment && <p className="text-muted">{assessment.assessment}</p>}
      <p>
        A team member has the full conversation, so you won&apos;t need to repeat anything. Expect a response <strong>{c.expected_response}</strong>.
      </p>
      <PolicyRefs refs={assessment?.policy_refs} />
    </Shell>
  );
}

function PolicyCard({ d }: { d: any }) {
  if (!d.found) return null;
  return (
    <div className="rise flex max-w-[92%] flex-wrap gap-1.5">
      {d.sections.map((s: any) => (
        <details key={s.policy} className="group rounded-xl border border-line bg-surface px-3 py-1.5 text-xs open:w-full">
          <summary className="cursor-pointer font-semibold text-dusk">
            Policy {s.policy} · {humanize(s.title.toLowerCase())}
          </summary>
          <p className="mt-1.5 text-muted">{s.text}</p>
        </details>
      ))}
    </div>
  );
}

function PropertyCard({ d }: { d: any }) {
  return (
    <Shell eyebrow={`${d.city}, ${d.state} · ${d.market_type}`} title={d.property_name}>
      <ul className="grid grid-cols-2 gap-x-4 gap-y-1 text-xs">
        {d.room_types.filter((r: any) => r.base_rate).map((r: any) => (
          <li key={r.room_type} className="flex justify-between gap-2">
            <span className="text-muted">{r.room_type}</span>
            <span>{money(r.base_rate, false)}</span>
          </li>
        ))}
      </ul>
      {d.max_meeting_capacity && <p className="text-xs text-muted">Meeting space for up to {d.max_meeting_capacity} guests</p>}
    </Shell>
  );
}
