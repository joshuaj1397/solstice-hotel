"use client";
/* eslint-disable @typescript-eslint/no-explicit-any */

import { useEffect, useId, useState } from "react";
import { Chip, Spinner, humanize } from "@/components/ui";
import { money } from "@/lib/dates";
import { Stat } from "./Queue";

const P95_TARGET_MS = 2500;

export function Metrics() {
  const [m, setM] = useState<any>(null);
  useEffect(() => {
    const load = () => fetch("/api/staff/metrics").then((r) => (r.ok ? r.json() : null)).then((j) => j && setM(j));
    load();
    const t = setInterval(load, 10000);
    return () => clearInterval(t);
  }, []);
  if (!m) return <Spinner label="Loading metrics" />;

  const f = Object.fromEntries(m.funnel.map((r: any) => [r.event, r]));
  const n = (k: string) => f[k]?.n ?? 0;
  const funnel = [
    { label: "Conversations", value: m.sessions ?? 0 },
    { label: "Availability shown", value: n("availability_shown") },
    { label: "Rooms held", value: n("hold_created") },
    { label: "Bookings confirmed", value: n("booking_confirmed") },
  ];
  const llm = m.latency_by_path.find((r: any) => r.path === "llm");
  const llmOk = llm ? llm.p95 <= P95_TARGET_MS : null;

  return (
    <div className="space-y-6">
      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        <Stat label="Containment rate" value={m.containment_rate != null ? `${Math.round(m.containment_rate * 100)}%` : "—"} hint="conversations resolved without a hand-off" />
        <Stat label="Bookings from chat" value={n("booking_confirmed")} hint={`${money(f.booking_confirmed?.usd ?? 0, false)} room revenue before tax`} />
        <Stat label="Concierge p95 (LLM path)" value={llm ? `${(llm.p95 / 1000).toFixed(1)}s` : "—"}
          hint={llmOk == null ? "no turns yet" : <>target ≤ {P95_TARGET_MS / 1000}s · {llmOk ? <Chip tone="ok">✓ on target</Chip> : <Chip tone="bad">⚑ over target</Chip>}</>} />
        <Stat label="Booking Rescue offers" value={n("rescue_offered")} hint={`${n("proposal_generated")} group proposals generated`} />
      </div>

      <section className="card p-5" aria-labelledby="funnel-h">
        <h2 id="funnel-h" className="text-xl font-semibold">Reservation funnel</h2>
        <p className="mb-4 text-sm text-muted">Concierge and booking events since the stack started. Each bar is a count of events at that stage.</p>
        <BarChart data={funnel} unit="events" />
      </section>

      <div className="grid gap-6 lg:grid-cols-2">
        <section className="card p-5" aria-labelledby="lat-h">
          <h2 id="lat-h" className="mb-3 text-xl font-semibold">Latency by path</h2>
          <div className="table-wrap border border-line" role="region" tabIndex={0} aria-labelledby="lat-h">
            <table>
              <thead><tr><th>Path</th><th>Turns</th><th>p50</th><th>p95</th></tr></thead>
              <tbody>
                {m.latency_by_path.map((r: any) => (
                  <tr key={r.path}>
                    <th scope="row">{PATH_LABEL[r.path] ?? r.path}</th>
                    <td data-label="Turns" className="tabular-nums">{r.n}</td>
                    <td data-label="p50" className="tabular-nums">{r.p50} ms</td>
                    <td data-label="p95" className="tabular-nums">{r.p95} ms</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <p className="mt-2 text-xs text-muted">Safety triage skips the model entirely. Degraded means the model was unavailable and policy search answered instead.</p>
        </section>

        <section className="card p-5" aria-labelledby="gr-h">
          <h2 id="gr-h" className="mb-3 text-xl font-semibold">Guardrail activations</h2>
          {m.guardrails.length === 0 ? <p className="text-sm text-muted">None yet.</p> : (
            <div className="table-wrap border border-line" role="region" tabIndex={0} aria-labelledby="gr-h">
              <table>
                <thead><tr><th>Guardrail</th><th>Count</th></tr></thead>
                <tbody>
                  {m.guardrails.map((g: any) => (
                    <tr key={g.kind}><th scope="row">{GUARD_LABEL[g.kind] ?? humanize(g.kind)}</th><td data-label="Count" className="tabular-nums">{g.n}</td></tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
          <h3 className="mb-2 mt-5 font-sans font-semibold">Group proposals</h3>
          <ul className="flex flex-wrap gap-2 text-sm">
            {m.proposals.map((p: any) => (
              <li key={p.status} className="rounded-xl border border-line px-3 py-2">
                <span className="font-semibold tabular-nums">{p.n}</span> {humanize(p.status)}
                {p.avg_ms ? <span className="text-xs text-muted"> · avg {(p.avg_ms / 1000).toFixed(1)}s</span> : null}
              </li>
            ))}
          </ul>
        </section>
      </div>

      <section className="card p-5" aria-labelledby="dq-h">
        <h2 id="dq-h" className="text-xl font-semibold">Data quality issues caught at ingestion</h2>
        <p className="mb-3 text-sm text-muted">Bad source values are quarantined, so the agent can never quote them.</p>
        <div className="table-wrap border border-line" role="region" tabIndex={0} aria-labelledby="dq-h">
          <table>
            <thead><tr><th>Record</th><th>Field</th><th>Value</th><th>Issue</th><th>Action</th></tr></thead>
            <tbody>
              {m.data_quality.map((d: any) => (
                <tr key={d.issue_id}>
                  <th scope="row" className="font-mono text-xs">{d.record_key}<span className="block font-sans font-normal text-muted">{d.source_file}</span></th>
                  <td data-label="Field" className="font-mono text-xs">{d.field}</td>
                  <td data-label="Value">{d.raw_value}</td>
                  <td data-label="Issue">{d.issue}</td>
                  <td data-label="Action" className="text-muted">{d.action}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>
    </div>
  );
}

const PATH_LABEL: Record<string, string> = { llm: "LLM (Gemma 4 E2B)", triage_bypass: "Safety triage (no LLM)", degraded: "Degraded mode", quick_action: "Quick action" };
const GUARD_LABEL: Record<string, string> = {
  pii_redacted: "Card/PII removed from guest message", tool_call_repaired: "Tool-call repair (model answered without acting)",
  blocked: "Reply replaced (unverified figure / note leak)", injection_attempt: "Prompt-injection attempt logged",
  ungrounded_figure: "Group note used an unverified figure",
};

/**
 * Single-series horizontal bar chart (dataviz skill): bars ≤24px with a 4px rounded data-end, square at the
 * baseline, a 2px surface gap, value at the tip in text tokens, and a per-bar hover/focus tooltip. The table
 * view carries every value without hovering.
 */
function BarChart({ data, unit }: { data: { label: string; value: number }[]; unit: string }) {
  const id = useId();
  const [active, setActive] = useState<number | null>(null);
  const max = Math.max(1, ...data.map((d) => d.value));
  return (
    <div>
      <ul className="space-y-[2px]" aria-describedby={`${id}-table`}>
        {data.map((d, i) => {
          const pct = (d.value / max) * 100;
          const prev = i > 0 ? data[i - 1].value : null;
          const conv = prev ? Math.round((d.value / prev) * 100) : null;
          return (
            <li
              key={d.label}
              tabIndex={0}
              onPointerEnter={() => setActive(i)}
              onPointerLeave={() => setActive(null)}
              onFocus={() => setActive(i)}
              onBlur={() => setActive(null)}
              className="relative grid grid-cols-[9.5rem_1fr] items-center gap-3 rounded-md py-1.5 outline-offset-2 hover:bg-sunken/60 focus-visible:bg-sunken/60"
              aria-label={`${d.label}: ${d.value} ${unit}${conv != null ? `, ${conv}% of previous stage` : ""}`}
            >
              <span className="truncate text-sm text-muted">{d.label}</span>
              <span className="flex items-center gap-2 border-s border-[var(--color-grid)]">
                <span
                  className="block h-5 rounded-e-[4px] transition-[width] duration-500"
                  style={{ width: `max(${pct}%, 2px)`, background: "var(--color-viz)", filter: active === i ? "brightness(1.12)" : undefined }}
                />
                <span className="text-sm font-semibold tabular-nums text-ink">{d.value}</span>
              </span>
              {active === i && (
                <span role="tooltip" className="pointer-events-none absolute -top-9 left-40 z-10 rounded-lg border border-line bg-surface px-2.5 py-1 text-xs shadow-md">
                  <strong className="tabular-nums">{d.value}</strong> <span className="text-muted">{unit} · {d.label}</span>
                  {conv != null && <span className="text-muted"> · {conv}% of previous</span>}
                </span>
              )}
            </li>
          );
        })}
      </ul>
      <details className="mt-3 text-sm" id={`${id}-table`}>
        <summary className="cursor-pointer text-muted">View as table</summary>
        <table className="mt-2 w-full text-start">
          <thead><tr><th className="text-start">Stage</th><th className="text-end">Count</th><th className="text-end">vs previous</th></tr></thead>
          <tbody>
            {data.map((d, i) => (
              <tr key={d.label}><td>{d.label}</td><td className="text-end tabular-nums">{d.value}</td><td className="text-end tabular-nums">{i && data[i - 1].value ? `${Math.round((d.value / data[i - 1].value) * 100)}%` : "—"}</td></tr>
            ))}
          </tbody>
        </table>
      </details>
    </div>
  );
}
