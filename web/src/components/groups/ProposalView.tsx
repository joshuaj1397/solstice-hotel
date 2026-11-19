"use client";
/* eslint-disable @typescript-eslint/no-explicit-any */

import { useId } from "react";
import { money } from "@/lib/dates";
import { Chip, PlainDate, humanize, statusTone } from "@/components/ui";

const ICON: Record<string, string> = { pass: "✓", fail: "⚑", warn: "!", info: "i" };
const CHECK_TONE: Record<string, "ok" | "bad" | "warn" | "muted"> = { pass: "ok", fail: "bad", warn: "warn", info: "muted" };

export function ProposalView({
  result,
  audience,
  onReview,
  reviewing,
}: {
  result: any;
  audience: "client" | "staff";
  onReview?: (option: string) => void;
  reviewing?: boolean;
}) {
  const d = result.decision;
  const p = d.pricing;
  const req = d.requirements;
  const id = useId();
  const staff = audience === "staff";
  const headline =
    result.status === "auto_approved"
      ? "Proposal ready · rooms on hold"
      : result.status === "needs_clarification"
        ? "A few quick questions"
        : staff
          ? "Needs your review"
          : "Our team is reviewing a few details";

  return (
    <article className="space-y-5" aria-labelledby={`${id}-h`}>
      <header className="flex flex-wrap items-center gap-2">
        <h3 id={`${id}-h`} className="text-2xl font-semibold">{headline}</h3>
        <Chip tone={statusTone(result.status)}>{humanize(result.status)}</Chip>
        {d.priority === "urgent" && <Chip tone="bad">Urgent · {d.priority_reason}</Chip>}
        <span className="ms-auto font-mono text-xs text-muted">
          {result.proposal_id} · {d.inquiry_id}
          {result.latency_ms ? ` · ${(result.latency_ms / 1000).toFixed(1)}s` : ""}
        </span>
      </header>

      {d.property && req.arrival && (
        <p className="text-sm text-muted">
          <strong className="text-ink">{d.company}</strong> · {d.event_type} · {d.property.property_name} ·{" "}
          <PlainDate iso={req.arrival} year={false} /> → <PlainDate iso={req.departure} /> · {req.rooms} × {req.room_type}
        </p>
      )}

      {d.missing?.length > 0 && (
        <section className="rounded-2xl border border-dusk/30 bg-dusk-soft p-4">
          <h4 className="font-sans font-semibold text-dusk">We need these to price your block</h4>
          <ul className="mt-2 list-disc space-y-1 ps-5 text-sm">
            {[...d.missing, ...(d.optional_questions ?? [])].map((m: any) => <li key={m.field + m.question}>{m.question}</li>)}
          </ul>
        </section>
      )}

      {d.hold && (
        <p className="rounded-xl bg-ok-soft p-3 text-sm text-ok">
          ✓ {req.rooms} rooms held for {d.hold.hours} hours (until {d.hold.expires_at.slice(0, 16).replace("T", " ")}). No GM review needed: every rule passed.
        </p>
      )}

      {p && (
        <section aria-labelledby={`${id}-pricing`}>
          <h4 id={`${id}-pricing`} className="mb-2 font-sans font-semibold">
            Pricing <span className="font-normal text-muted">· base {money(p.base_rate)} · ceiling {p.effective_ceiling_pct}% ({p.ceiling_reason})</span>
          </h4>
          <div className="table-wrap border border-line" role="region" tabIndex={0} aria-labelledby={`${id}-pricing`}>
            <table>
              <thead>
                <tr><th>Option</th><th>Discount</th><th>Rate / night</th><th>Total ({p.room_nights} room-nights)</th><th>Approval</th>{staff && <th />}</tr>
              </thead>
              <tbody>
                {p.options.map((o: any) => (
                  <tr key={o.label}>
                    <th scope="row">{o.label}<span className="block text-xs font-normal text-muted">{o.note}</span></th>
                    <td data-label="Discount">{o.discount_pct}%</td>
                    <td data-label="Rate">{money(o.rate)}{o.within_budget === false && <span className="block text-xs text-warn">above budget</span>}{o.within_budget === true && <span className="block text-xs text-ok">within budget</span>}</td>
                    <td data-label="Total">{money(o.subtotal, false)} <span className="text-xs text-muted">+ tax</span></td>
                    <td data-label="Approval">{o.auto_approvable ? <Chip tone="ok">Confirm today</Chip> : <Chip tone="warn">GM review</Chip>}</td>
                    {staff && (
                      <td>
                        {onReview && result.status === "needs_review" && o.auto_approvable && (
                          <button type="button" className="btn btn-ghost !py-1 !text-xs" disabled={reviewing} onClick={() => onReview("requested")}>
                            Approve
                          </button>
                        )}
                      </td>
                    )}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>
      )}

      {d.alternatives?.length > 0 && (
        <section>
          <h4 className="mb-2 font-sans font-semibold">
            Booking Rescue <span className="font-normal text-muted">· options we can offer instead</span>
          </h4>
          <ul className="grid gap-2 sm:grid-cols-2">
            {d.alternatives.map((a: any, i: number) => (
              <li key={i} className="rounded-xl border border-sun/30 bg-sun-soft/50 p-3 text-sm">
                <p className="font-semibold">{a.label}</p>
                <p className="text-muted">
                  {a.rooms} × {a.room_type} · <PlainDate iso={a.arrival} year={false} />–<PlainDate iso={a.departure} year={false} /> · {money(a.rate)} ({a.discount_pct}%)
                  {a.client_consent_needed ? " · client asked for their preferred hotel only" : ""}
                </p>
                <div className="mt-2 flex items-center gap-2">
                  {a.auto_approvable ? <Chip tone="ok">Confirmable today</Chip> : <Chip tone="warn">Needs approval</Chip>}
                  {staff && onReview && result.status === "needs_review" && (
                    <button type="button" className="btn btn-ghost ms-auto !py-1 !text-xs" disabled={reviewing} onClick={() => onReview(`alternative:${i}`)}>
                      Approve & hold
                    </button>
                  )}
                </div>
              </li>
            ))}
          </ul>
        </section>
      )}

      {d.conditions?.length > 0 && (
        <p className="rounded-xl bg-warn-soft p-3 text-sm text-warn">
          Before confirming: {d.conditions.map((c: any) => c.detail).join(" ")}
        </p>
      )}

      {staff && d.checks?.length > 0 && (
        <section aria-labelledby={`${id}-checks`}>
          <h4 id={`${id}-checks`} className="mb-2 font-sans font-semibold">Rule checks <span className="font-normal text-muted">· deterministic, grounded in property data</span></h4>
          <div className="table-wrap border border-line" role="region" tabIndex={0} aria-labelledby={`${id}-checks`}>
            <table>
              <thead><tr><th>Check</th><th>Result</th><th>Detail</th><th>Source</th></tr></thead>
              <tbody>
                {d.checks.map((c: any, i: number) => (
                  <tr key={i}>
                    <th scope="row">{c.label}</th>
                    <td data-label="Result"><Chip tone={CHECK_TONE[c.status]}>{ICON[c.status]} {c.severity}</Chip></td>
                    <td data-label="Detail">{c.detail}</td>
                    <td data-label="Source" className="font-mono text-xs text-muted">{c.ref ?? ""}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>
      )}

      {result.cover_note && (
        <section className="rounded-2xl border border-line bg-surface p-4">
          <p className="eyebrow">{staff ? "Draft to client · written by the LLM, figures verified by code" : "Note from Solstice Group Sales"}</p>
          <p className="mt-1 font-semibold">{result.cover_note.subject}</p>
          <p className="mt-2 whitespace-pre-wrap text-sm">{result.cover_note.body}</p>
        </section>
      )}

      {staff && result.trace?.length > 0 && (
        <details className="rounded-xl border border-line p-3 text-sm">
          <summary className="cursor-pointer font-semibold">Agent trace</summary>
          <ol className="mt-2 list-decimal space-y-1 ps-5 text-muted">
            {result.trace.map((t: any, i: number) => <li key={i}><strong className="text-ink">{t.node}</strong>: {t.summary}</li>)}
          </ol>
        </details>
      )}
    </article>
  );
}
