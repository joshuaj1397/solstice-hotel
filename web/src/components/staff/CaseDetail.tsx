"use client";
/* eslint-disable @typescript-eslint/no-explicit-any */

import Link from "next/link";
import { useParams } from "next/navigation";
import { useEffect, useState, type FormEvent } from "react";
import { toast } from "@/components/Toaster";
import { Chip, PlainDate, Spinner, TierBadge, humanize, statusTone } from "@/components/ui";
import { formatTimestamp, loadTemporal, money } from "@/lib/dates";

/** The hand-off packet: everything a human needs to act without asking the guest to repeat themselves. */
export function CaseDetail() {
  const { id } = useParams<{ id: string }>();
  const [c, setC] = useState<any>(null);
  const [busy, setBusy] = useState(false);
  useEffect(() => {
    let alive = true;
    loadTemporal()
      .then(() => fetch(`/api/staff/escalations/${id}`))
      .then((r) => (r.ok ? r.json() : null))
      .then((j) => alive && j && setC(j));
    return () => {
      alive = false;
    };
  }, [id]);

  const reply = async (e: FormEvent<HTMLFormElement>) => {
    e.preventDefault();
    const form = e.currentTarget;
    const f = new FormData(form);
    setBusy(true);
    const r = await fetch(`/api/staff/escalations/${id}/reply`, {
      method: "POST", headers: { "content-type": "application/json" },
      body: JSON.stringify({ body: f.get("body"), resolve: f.get("resolve") === "on" }),
    });
    setBusy(false);
    if (r.ok) { setC(await r.json()); form.reset(); toast("Reply sent. The guest sees it in their conversation.", "ok"); }
  };

  if (!c) return <Spinner label="Loading case" />;
  const a = c.agent_assessment ?? {};
  return (
    <div className="grid gap-6 lg:grid-cols-12">
      <div className="space-y-4 lg:col-span-7">
        <Link href="/staff" className="text-sm text-muted hover:text-ink">← Queue</Link>
        <section className="card p-5">
          <div className="flex flex-wrap items-center gap-2">
            <h2 className="font-mono text-2xl font-semibold">{c.case_id}</h2>
            <Chip tone={statusTone(c.severity)}>{humanize(c.severity)}</Chip>
            <Chip tone={statusTone(c.status)}>{humanize(c.status)}</Chip>
            <span className="ms-auto text-xs text-muted">Due {formatTimestamp(c.sla_due_at)}</span>
          </div>
          <p className="mt-1 text-sm text-muted">{humanize(c.category)} · routed to <strong className="text-ink">{c.route_to}</strong></p>
          <blockquote className="mt-4 rounded-xl border-s-4 border-sun bg-sun-soft/50 p-3 text-sm">“{c.guest_ask}”</blockquote>
          <dl className="mt-4 grid gap-3 text-sm sm:grid-cols-2">
            <div className="sm:col-span-2"><dt className="eyebrow">Agent summary</dt><dd>{c.summary}</dd></div>
            {a.assessment && <div className="sm:col-span-2"><dt className="eyebrow">Policy assessment</dt><dd>{a.assessment}</dd></div>}
            {c.recommended_action && <div className="sm:col-span-2"><dt className="eyebrow">Recommended action</dt><dd className="font-medium text-dusk">{c.recommended_action}</dd></div>}
            {a.eligible !== undefined && a.eligible !== null && <div><dt className="eyebrow">Refund/comp eligible</dt><dd>{a.eligible ? "Yes" : "No"}</dd></div>}
            {a.service_recovery_window_ends && <div><dt className="eyebrow">72h window ends</dt><dd>{a.service_recovery_window_ends.replace("T", " ").slice(0, 16)}</dd></div>}
            {a.staff_guidance && <div className="sm:col-span-2"><dt className="eyebrow">Front-desk note on file</dt><dd className="text-muted">{a.staff_guidance}</dd></div>}
            {c.policy_refs?.length > 0 && <div className="sm:col-span-2"><dt className="eyebrow">Policies</dt><dd className="flex gap-1">{c.policy_refs.map((p: number) => <Chip key={p} tone="dusk">Policy {p}</Chip>)}</dd></div>}
          </dl>
        </section>

        <section className="card p-5" aria-labelledby="tx">
          <h3 id="tx" className="text-lg font-semibold">Conversation so far</h3>
          <ol className="mt-3 space-y-2 text-sm">
            {(c.transcript ?? []).map((t: any, i: number) => (
              <li key={i} className={`rounded-xl px-3 py-2 ${t.role === "guest" ? "bg-dusk-soft" : "bg-sunken"}`}>
                <span className="eyebrow">{t.role === "guest" ? "Guest" : "Sol"}</span>
                <p className="whitespace-pre-wrap">{t.text}</p>
              </li>
            ))}
            {c.messages.map((m: any) => (
              <li key={m.message_id} className="rounded-xl bg-ok-soft px-3 py-2">
                <span className="eyebrow !text-ok">{m.author_name} · {formatTimestamp(m.created_at)}</span>
                <p className="whitespace-pre-wrap">{m.body}</p>
              </li>
            ))}
          </ol>
          {c.status !== "resolved" && (
            <form onSubmit={reply} className="mt-4 space-y-2">
              <label className="label" htmlFor="reply-body">Reply to the guest (appears in their chat)</label>
              <textarea id="reply-body" name="body" rows={3} className="input" required maxLength={2000} />
              <div className="flex items-center gap-3">
                <label className="flex items-center gap-2 text-sm"><input type="checkbox" name="resolve" /> Resolve case</label>
                <button type="submit" className="btn btn-dusk ms-auto" disabled={busy}>{busy ? <Spinner label="Sending" /> : "Send reply"}</button>
              </div>
            </form>
          )}
        </section>
      </div>

      <aside className="space-y-4 lg:col-span-5">
        <section className="card p-5">
          <p className="eyebrow">Guest</p>
          {c.first_name ? (
            <>
              <h3 className="mt-1 flex items-center gap-2 text-xl font-semibold">{c.first_name} {c.last_name} <TierBadge tier={c.loyalty_tier} /></h3>
              <p className="text-sm text-muted">{c.loyalty_points?.toLocaleString()} points</p>
            </>
          ) : <p className="mt-1 text-sm text-muted">Not signed in (anonymous chat)</p>}
        </section>
        {c.reservation_id && (
          <section className="card p-5 text-sm">
            <p className="eyebrow">Reservation {c.reservation_id}</p>
            <h3 className="mt-1 text-lg font-semibold">{c.property_name}</h3>
            <p className="text-muted"><PlainDate iso={c.check_in} year={false} /> → <PlainDate iso={c.check_out} /> · {c.room_type}</p>
            <p className="text-muted">{c.rate_plan} · {c.nightly_rate > 0 ? money(c.nightly_rate) : "points"} · {c.reservation_status}</p>
            {c.internal_notes && <p className="mt-2 rounded-lg bg-warn-soft p-2 text-xs text-warn">{c.internal_notes}</p>}
          </section>
        )}
        <p className="text-xs text-muted">Card data is never shown here. Staff see contact details through the PMS, under its own access controls.</p>
      </aside>
    </div>
  );
}
