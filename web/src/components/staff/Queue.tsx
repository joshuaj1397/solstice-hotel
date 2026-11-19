"use client";
/* eslint-disable @typescript-eslint/no-explicit-any */

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import { toast } from "@/components/Toaster";
import { Chip, EmptyState, Spinner, TierBadge, humanize, statusTone } from "@/components/ui";
import { formatTimestamp, loadTemporal } from "@/lib/dates";

export function Queue() {
  const [q, setQ] = useState<any>(null);
  const load = useCallback(async () => {
    await loadTemporal();
    const r = await fetch("/api/staff/queue");
    if (r.ok) setQ(await r.json());
  }, []);
  useEffect(() => {
    // First load via a 0 ms timer, so setState never runs synchronously in the effect body; then poll.
    const first = setTimeout(load, 0);
    const t = setInterval(load, 8000);
    return () => {
      clearTimeout(first);
      clearInterval(t);
    };
  }, [load]);

  const decide = async (id: string, status: "approved" | "declined") => {
    const r = await fetch(`/api/staff/requests/${id}/decide`, {
      method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ status }),
    });
    if (r.ok) { toast(`${id} ${status}`, status === "approved" ? "ok" : "warn"); load(); }
  };

  if (!q) return <Spinner label="Loading queue" />;
  const open = q.escalations.filter((e: any) => e.status !== "resolved");
  const pending = q.requests.filter((r: any) => r.status === "pending_desk");
  const reviews = q.proposals.filter((p: any) => ["needs_review", "needs_clarification"].includes(p.status));

  return (
    <div className="space-y-6">
      <div className="grid gap-3 sm:grid-cols-3">
        <Stat label="Open hand-offs" value={open.length} hint={`${open.filter((e: any) => e.severity === "immediate").length} immediate`} />
        <Stat label="Desk approvals waiting" value={pending.length} hint="late check-out, early check-in, upgrades" />
        <Stat label="Group proposals to review" value={reviews.length} hint={<Link className="underline" href="/staff/groups">Open group sales →</Link>} />
      </div>

      <section className="card p-5" aria-labelledby="esc-h">
        <h2 id="esc-h" className="mb-3 text-xl font-semibold">Hand-offs from Sol</h2>
        {q.escalations.length === 0 ? (
          <EmptyState title="No hand-offs yet">When Sol can&apos;t resolve something, it lands here with the full context.</EmptyState>
        ) : (
          <div className="table-wrap border border-line" role="region" tabIndex={0} aria-labelledby="esc-h">
            <table>
              <thead><tr><th>Case</th><th>Severity</th><th>Guest</th><th>Category</th><th>Routed to</th><th>Due</th><th>Status</th></tr></thead>
              <tbody>
                {q.escalations.map((e: any) => (
                  <tr key={e.case_id} className={e.status === "resolved" ? "opacity-60" : ""}>
                    <th scope="row"><Link href={`/staff/cases/${e.case_id}`} className="font-mono text-dusk underline-offset-2 hover:underline">{e.case_id}</Link></th>
                    <td data-label="Severity"><Chip tone={statusTone(e.severity)}>{humanize(e.severity)}</Chip></td>
                    <td data-label="Guest">{e.guest_name ?? "Anonymous"} {e.loyalty_tier && <TierBadge tier={e.loyalty_tier} />}<span className="block text-xs text-muted">{e.property_name}</span></td>
                    <td data-label="Category">{humanize(e.category)}<span className="block max-w-xs truncate text-xs text-muted">{e.guest_ask}</span></td>
                    <td data-label="Routed to">{e.route_to}</td>
                    <td data-label="Due">{formatTimestamp(e.sla_due_at)}</td>
                    <td data-label="Status"><Chip tone={statusTone(e.status)}>{humanize(e.status)}</Chip></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>

      <section className="card p-5" aria-labelledby="req-h">
        <h2 id="req-h" className="mb-3 text-xl font-semibold">Front desk requests</h2>
        {q.requests.length === 0 ? (
          <EmptyState title="No requests yet" />
        ) : (
          <div className="table-wrap border border-line" role="region" tabIndex={0} aria-labelledby="req-h">
            <table>
              <thead><tr><th>Request</th><th>Guest</th><th>Ask</th><th>Policy decision</th><th>Status</th><th>Action</th></tr></thead>
              <tbody>
                {q.requests.map((r: any) => (
                  <tr key={r.request_id}>
                    <th scope="row" className="font-mono">{r.request_id}</th>
                    <td data-label="Guest">{r.guest_name} <TierBadge tier={r.loyalty_tier} /><span className="block text-xs text-muted">{r.property_name} · {r.reservation_id}</span></td>
                    <td data-label="Ask">{humanize(r.kind)}{r.details?.requested_time ? ` · ${r.details.requested_time}` : ""}{r.details?.details ? ` · ${r.details.details}` : ""}</td>
                    <td data-label="Policy decision" className="max-w-sm text-xs text-muted">{r.details?.explanation}</td>
                    <td data-label="Status"><Chip tone={statusTone(r.status)}>{r.decided_by?.startsWith("policy:") ? "Auto-confirmed by policy" : humanize(r.status)}</Chip></td>
                    <td data-label="Action">
                      {r.status === "pending_desk" && (
                        <span className="flex gap-1">
                          <button type="button" className="btn btn-primary !py-1 !text-xs" onClick={() => decide(r.request_id, "approved")}>Approve</button>
                          <button type="button" className="btn btn-ghost !py-1 !text-xs" onClick={() => decide(r.request_id, "declined")}>Decline</button>
                        </span>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>
    </div>
  );
}

export function Stat({ label, value, hint }: { label: string; value: React.ReactNode; hint?: React.ReactNode }) {
  return (
    <div className="card p-4">
      <p className="eyebrow">{label}</p>
      <p className="mt-1 font-display text-4xl font-semibold tabular-nums">{value}</p>
      {hint && <p className="mt-1 text-xs text-muted">{hint}</p>}
    </div>
  );
}
