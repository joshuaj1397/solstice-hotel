"use client";

import { Spinner } from "@/components/ui";

export type Step = { node: string; ms: number; route?: string | null };

const LABEL: Record<string, { label: string; kind: "code" | "llm" }> = {
  intake: { label: "Intake", kind: "code" },
  extract: { label: "Read email", kind: "llm" },
  register: { label: "Verify & save", kind: "code" },
  evaluate: { label: "Rules engine", kind: "code" },
  rescue_node: { label: "Booking Rescue", kind: "code" },
  hold_block: { label: "Hold rooms", kind: "code" },
  proposal_prompt: { label: "Assemble facts", kind: "code" },
  clarification_prompt: { label: "List questions", kind: "code" },
  proposal_writer: { label: "Write cover note", kind: "llm" },
  clarification_writer: { label: "Write email", kind: "llm" },
  finalize: { label: "Grounding check & save", kind: "code" },
};

/** Live view of the ADK workflow graph as step events stream in. */
export function Pipeline({ steps, running }: { steps: Step[]; running: boolean }) {
  const seen = steps.filter((s, i) => steps.findIndex((x) => x.node === s.node) === i && LABEL[s.node]);
  return (
    <ol className="flex flex-wrap items-center gap-x-1 gap-y-2" aria-label="Agent workflow progress">
      {seen.map((s, i) => {
        const meta = LABEL[s.node];
        const prev = i ? seen[i - 1].ms : 0;
        return (
          <li key={s.node} className="rise flex items-center gap-1">
            {i > 0 && <span aria-hidden className="text-muted">→</span>}
            <span
              className={`chip border ${meta.kind === "llm" ? "border-dusk/40 bg-dusk-soft text-dusk" : "border-line bg-surface text-ink"}`}
              title={meta.kind === "llm" ? "LLM step (Gemma 4 E2B)" : "Deterministic step"}
            >
              {meta.kind === "llm" ? "✦" : "✓"} {meta.label}
              {s.route && <span className="text-muted">· {s.route}</span>}
              <span className="font-mono text-[10px] text-muted">{Math.max(0, s.ms - prev)}ms</span>
            </span>
          </li>
        );
      })}
      {running && (
        <li className="flex items-center gap-1.5 text-xs text-muted">
          <span aria-hidden>→</span>
          <Spinner label="Workflow running" /> working…
        </li>
      )}
    </ol>
  );
}

export function PipelineLegend() {
  return (
    <p className="text-xs text-muted">
      <span className="chip border border-line bg-surface">✓ deterministic</span>{" "}
      <span className="chip border border-dusk/40 bg-dusk-soft text-dusk">✦ LLM (output verified by code)</span>
    </p>
  );
}
