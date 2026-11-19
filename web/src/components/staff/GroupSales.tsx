"use client";
/* eslint-disable @typescript-eslint/no-explicit-any */

import { useCallback, useEffect, useState } from "react";
import { readSse } from "@/lib/sse";
import { toast } from "@/components/Toaster";
import { Pipeline, PipelineLegend, type Step } from "@/components/groups/Pipeline";
import { ProposalView } from "@/components/groups/ProposalView";
import { Chip, PlainDate, Spinner, humanize, statusTone } from "@/components/ui";

/** Group sales desk: run the agent on portal inquiries, then review flagged proposals in one click. */
export function GroupSales() {
  const [rows, setRows] = useState<any[]>([]);
  const [active, setActive] = useState<string | null>(null);
  const [steps, setSteps] = useState<Step[]>([]);
  const [running, setRunning] = useState(false);
  const [result, setResult] = useState<any>(null);
  const [reviewing, setReviewing] = useState(false);

  const load = useCallback(async () => {
    const r = await fetch("/api/group/inquiries");
    if (r.ok) setRows(await r.json());
  }, []);
  useEffect(() => {
    let alive = true;
    fetch("/api/group/inquiries")
      .then((r) => (r.ok ? r.json() : null))
      .then((j) => alive && j && setRows(j));
    return () => {
      alive = false;
    };
  }, []);

  const open = async (row: any) => {
    setActive(row.inquiry_id);
    setSteps([]);
    setResult(null);
    if (row.proposal_id) {
      const r = await fetch(`/api/group/proposals/${row.proposal_id}`);
      if (r.ok) {
        const p = await r.json();
        setResult({ proposal_id: p.proposal_id, status: p.status, decision: p.decision, cover_note: p.cover_note, trace: p.trace, latency_ms: p.latency_ms, priority: p.priority });
      }
    }
  };

  const run = async (iid: string) => {
    setActive(iid);
    setSteps([]);
    setResult(null);
    setRunning(true);
    try {
      const res = await fetch(`/api/group/inquiries/${iid}/run`, { method: "POST" });
      for await (const ev of readSse(res)) {
        if (ev.event === "step") setSteps((s) => [...s, ev.data as Step]);
        if (ev.event === "result") setResult(ev.data);
      }
    } finally {
      setRunning(false);
      load();
    }
  };

  const runAll = async () => {
    for (const r of rows.filter((x) => x.received_via === "web_portal" && !x.proposal_id)) await run(r.inquiry_id);
  };

  const review = async (option: string) => {
    if (!result) return;
    setReviewing(true);
    const r = await fetch(`/api/staff/proposals/${result.proposal_id}/review`, {
      method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ option }),
    });
    const j = await r.json();
    setReviewing(false);
    if (!r.ok) return toast(j.message ?? "Couldn't approve.", "bad");
    toast(`${result.proposal_id} ${j.status}: inventory held`, "ok");
    setResult({ ...result, status: j.status });
    load();
  };

  return (
    <div className="grid gap-6 lg:grid-cols-12">
      <section className="card p-4 lg:col-span-4" aria-labelledby="inq-h">
        <div className="mb-3 flex items-center gap-2">
          <h2 id="inq-h" className="text-xl font-semibold">Inquiries</h2>
          <button type="button" className="btn btn-ghost ms-auto !py-1 !text-xs" onClick={runAll} disabled={running}>Run agent on all new</button>
        </div>
        <ul className="space-y-1.5">
          {rows.map((r) => (
            <li key={r.inquiry_id}>
              <div className={`rounded-xl border p-3 text-sm ${active === r.inquiry_id ? "border-sun bg-sun-soft/40" : "border-line"}`}>
                <button type="button" className="w-full text-start" onClick={() => open(r)}>
                  <span className="flex items-center gap-2">
                    <span className="font-mono text-xs text-muted">{r.inquiry_id}</span>
                    {r.priority === "urgent" && <Chip tone="bad">Urgent</Chip>}
                    {r.proposal_status ? <Chip tone={statusTone(r.proposal_status)}>{humanize(r.proposal_status)}</Chip> : <Chip>New</Chip>}
                  </span>
                  <span className="mt-0.5 block font-semibold">{r.company_name}</span>
                  <span className="block text-xs text-muted">
                    {r.preferred_property_code} · {r.rooms_requested_raw ?? "?"} rooms · {r.arrival_date ? <PlainDate iso={r.arrival_date} /> : "no dates"}
                    {r.received_via === "email" ? " · via email" : ""}
                  </span>
                </button>
                <button type="button" className="btn btn-ghost mt-2 !py-1 !text-xs" disabled={running} onClick={() => run(r.inquiry_id)}>
                  {running && active === r.inquiry_id ? <Spinner label="Running" /> : r.proposal_id ? "Re-run agent" : "Run agent"}
                </button>
              </div>
            </li>
          ))}
        </ul>
      </section>
      <section className="card space-y-4 p-5 lg:col-span-8" aria-live="polite">
        <div className="flex items-center gap-2">
          <h2 className="text-xl font-semibold">{active ?? "Select an inquiry"}</h2>
          <span className="ms-auto"><PipelineLegend /></span>
        </div>
        {(steps.length > 0 || running) && <Pipeline steps={steps} running={running} />}
        {result ? (
          <>
            <ProposalView result={result} audience="staff" onReview={review} reviewing={reviewing} />
            {["needs_review", "needs_clarification", "auto_approved", "approved"].includes(result.status) && (
              <div className="flex flex-wrap gap-2 border-t border-line pt-4">
                {result.status === "needs_review" && <button type="button" className="btn btn-primary" disabled={reviewing} onClick={() => review("requested")}>Approve as requested (override)</button>}
                {result.status !== "approved" && <button type="button" className="btn btn-dusk" disabled={reviewing} onClick={() => review("send")}>Send to client</button>}
                {result.status === "needs_review" && <button type="button" className="btn btn-ghost" disabled={reviewing} onClick={() => review("decline")}>Decline</button>}
              </div>
            )}
          </>
        ) : (
          !running && <p className="text-sm text-muted">Run the agent to see feasibility checks, pricing, Booking Rescue options and a draft note.</p>
        )}
      </section>
    </div>
  );
}
