"use client";
/* eslint-disable @typescript-eslint/no-explicit-any */

import { useCallback, useEffect, useId, useRef, useState, type FormEvent, type KeyboardEvent } from "react";
import { readSse } from "@/lib/sse";
import { toast } from "@/components/Toaster";
import { Spinner } from "@/components/ui";
import { CardView } from "./Cards";

type Turn = {
  id: string;
  role: "guest" | "agent" | "staff" | "notice";
  text: string;
  cards: { kind: string; data: any }[];
  meta?: { latency_ms?: number; path?: string; tools?: string[]; route?: { tool: string; reason: string }; guardrail?: string | null; degraded?: boolean };
};

export type ConciergeProps = {
  greeting: string;
  prompts: string[];
  onChange?: () => void;
  /** Lets the parent push a message (e.g. a stay-card button) into the conversation. */
  externalAsk?: { text: string; nonce: number } | null;
};

const uid = () => Math.random().toString(36).slice(2);

export function Concierge({ greeting, prompts, onChange, externalAsk }: ConciergeProps) {
  const [sid, setSid] = useState<string | null>(null);
  const [turns, setTurns] = useState<Turn[]>([{ id: "hello", role: "agent", text: greeting, cards: [] }]);
  const [busy, setBusy] = useState(false);
  const [status, setStatus] = useState<string | null>(null);
  const [internals, setInternals] = useState(false);
  const [draft, setDraft] = useState("");
  const [offline, setOffline] = useState(false);
  const formRef = useRef<HTMLFormElement>(null);
  const logRef = useRef<HTMLDivElement>(null);
  const lastUpdate = useRef(0);
  const inputId = useId();

  useEffect(() => {
    let cancelled = false;
    fetch("/api/concierge", { method: "POST" })
      .then((r) => (r.ok ? r.json() : Promise.reject(r)))
      .then((j) => !cancelled && setSid(j.session_id))
      .catch(() => !cancelled && setOffline(true));
    return () => {
      cancelled = true;
    };
  }, []);

  // Hand-offs are two-way: poll for staff replies on cases opened from this conversation.
  useEffect(() => {
    if (!sid) return;
    const t = setInterval(async () => {
      const r = await fetch(`/api/concierge/${sid}/updates?after=${lastUpdate.current}`).catch(() => null);
      if (!r?.ok) return;
      const updates: any[] = await r.json();
      if (!updates.length) return;
      lastUpdate.current = updates[updates.length - 1].message_id;
      setTurns((ts) => [
        ...ts,
        ...updates.map((u) => ({ id: `staff-${u.message_id}`, role: "staff" as const, text: u.body, cards: [], meta: { path: `${u.author_name} · ${u.case_id}` } })),
      ]);
      toast(`${updates[0].author_name} replied to case ${updates[0].case_id}`, "ok");
    }, 5000);
    return () => clearInterval(t);
  }, [sid]);

  useEffect(() => {
    logRef.current?.scrollTo({ top: logRef.current.scrollHeight, behavior: "smooth" });
  }, [turns, status]);

  const send = useCallback(
    async (text: string) => {
      const clean = text.trim();
      if (!clean || !sid || busy) return;
      setBusy(true);
      setDraft("");
      const agentId = uid();
      setTurns((ts) => [...ts, { id: uid(), role: "guest", text: clean, cards: [] }, { id: agentId, role: "agent", text: "", cards: [], meta: {} }]);
      const patch = (fn: (t: Turn) => Turn) => setTurns((ts) => ts.map((t) => (t.id === agentId ? fn(t) : t)));
      try {
        const res = await fetch(`/api/concierge/${sid}/messages`, {
          method: "POST",
          headers: { "content-type": "application/json" },
          body: JSON.stringify({ text: clean }),
        });
        if (!res.ok) throw new Error((await res.json().catch(() => ({}))).message ?? "Something went wrong.");
        for await (const ev of readSse(res)) {
          const d: any = ev.data;
          if (ev.event === "status") setStatus(d.label);
          else if (ev.event === "route") patch((t) => ({ ...t, meta: { ...t.meta, route: d } }));
          else if (ev.event === "notice")
            setTurns((ts) => [...ts.slice(0, -1), { id: uid(), role: "notice", text: d.text, cards: [] }, ts[ts.length - 1]]);
          else if (ev.event === "card") patch((t) => ({ ...t, cards: [...t.cards, d.card] }));
          else if (ev.event === "message") patch((t) => ({ ...t, text: d.text, meta: { ...t.meta, guardrail: d.guardrail ?? null, degraded: d.degraded } }));
          else if (ev.event === "done") patch((t) => ({ ...t, meta: { ...t.meta, latency_ms: d.latency_ms, path: d.path, tools: d.tools } }));
        }
        onChange?.();
      } catch (err) {
        patch((t) => ({ ...t, text: err instanceof Error ? err.message : "Something went wrong. Please try again." }));
      } finally {
        setBusy(false);
        setStatus(null);
      }
    },
    [sid, busy, onChange],
  );

  useEffect(() => {
    if (externalAsk) send(externalAsk.text);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [externalAsk?.nonce]);

  // modern-web-guidance (ime-safe-enter-submit): never submit while an IME is composing.
  const onKeyDown = (e: KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      if (e.nativeEvent.isComposing || e.keyCode === 229) return;
      formRef.current?.requestSubmit();
    }
  };
  const onSubmit = (e: FormEvent) => {
    e.preventDefault();
    send(draft);
  };

  return (
    <section aria-labelledby={`${inputId}-title`} className="card flex min-h-[32rem] flex-col overflow-hidden lg:h-[calc(100dvh-8.5rem)]">
      <header className="flex items-center gap-3 border-b border-line px-5 py-3">
        <span aria-hidden className="grid size-9 place-items-center rounded-full bg-dusk font-display text-lg text-on-accent">S</span>
        <div className="min-w-0">
          <h2 id={`${inputId}-title`} className="text-lg font-semibold leading-tight">Sol · your concierge</h2>
          <p className="text-xs text-muted">
            {offline ? "Offline — use the stay buttons or call the front desk" : sid ? "Answers from Solstice records and policy" : "Connecting…"}
          </p>
        </div>
        <label className="ms-auto flex cursor-pointer items-center gap-2 text-xs font-medium text-muted">
          <input type="checkbox" className="size-4" checked={internals} onChange={(e) => setInternals(e.target.checked)} />
          Agent internals
        </label>
      </header>

      <div ref={logRef} role="log" aria-live="polite" aria-relevant="additions" aria-label="Conversation" className="flex-1 space-y-4 overflow-y-auto px-5 py-4">
        {turns.map((t) => (
          <TurnView key={t.id} turn={t} internals={internals} onAsk={send} onChange={onChange} sessionId={sid} />
        ))}
        {busy && (
          <div className="flex items-center gap-2 text-sm text-muted" aria-live="polite">
            <Spinner label={status ?? "Sol is thinking"} />
            <span>{status ?? "Thinking"}…</span>
          </div>
        )}
      </div>

      <div className="border-t border-line bg-sunken/60 px-4 pb-4 pt-3">
        <div className="mb-2 flex gap-2 overflow-x-auto pb-1" role="group" aria-label="Suggested questions">
          {prompts.map((p) => (
            <button key={p} type="button" disabled={busy || !sid} onClick={() => send(p)} className="btn btn-ghost shrink-0 !py-1 !text-xs">
              {p}
            </button>
          ))}
        </div>
        <form ref={formRef} onSubmit={onSubmit} className="flex items-end gap-2">
          <label htmlFor={inputId} className="sr-only">
            Message Sol
          </label>
          <textarea
            id={inputId}
            rows={1}
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
            onKeyDown={onKeyDown}
            maxLength={2000}
            placeholder="Ask about your stay, policies, or book a room…"
            className="input max-h-40 min-h-11 resize-none [field-sizing:content]"
            enterKeyHint="send"
          />
          <button type="submit" className="btn btn-primary h-11" disabled={busy || !sid || !draft.trim()}>
            Send
          </button>
        </form>
        <p className="mt-2 text-[11px] text-muted">Never share card numbers in chat. Payment only happens in secure checkout.</p>
      </div>
    </section>
  );
}

function TurnView({ turn: t, internals, onAsk, onChange, sessionId }: { turn: Turn; internals: boolean; onAsk: (s: string) => void; onChange?: () => void; sessionId: string | null }) {
  if (t.role === "guest") {
    return (
      <div className="rise flex justify-end">
        <p className="max-w-[85%] whitespace-pre-wrap rounded-2xl rounded-br-md bg-dusk px-4 py-2.5 text-sm text-on-accent">{t.text}</p>
      </div>
    );
  }
  if (t.role === "notice") {
    return (
      <p className="rise rounded-xl border border-warn/40 bg-warn-soft px-3 py-2 text-xs text-warn" role="status">
        🛡️ {t.text}
      </p>
    );
  }
  if (t.role === "staff") {
    return (
      <div className="rise rounded-2xl border border-ok/40 bg-ok-soft px-4 py-3 text-sm">
        <p className="eyebrow !text-ok">Team member · {t.meta?.path}</p>
        <p className="mt-1 whitespace-pre-wrap">{t.text}</p>
      </div>
    );
  }
  const m = t.meta ?? {};
  return (
    <div className="rise space-y-2">
      {internals && m.route && (
        <p className="font-mono text-[11px] text-muted">🧭 router: {m.route.reason} → {m.route.tool}</p>
      )}
      {t.cards.map((c, i) => (
        <CardView key={i} kind={c.kind} data={c.data} onAsk={onAsk} onChange={onChange} sessionId={sessionId} internals={internals} />
      ))}
      {t.text && (
        <div className="max-w-[92%] rounded-2xl rounded-bl-md bg-sunken px-4 py-2.5 text-sm">
          <p className="whitespace-pre-wrap">{t.text}</p>
          {m.degraded && <p className="mt-1 text-[11px] font-semibold text-warn">Limited mode: answered from policy search without the AI model.</p>}
        </div>
      )}
      {internals && m.latency_ms != null && (
        <p className="font-mono text-[11px] text-muted">
          ⏱ {m.latency_ms} ms · path {m.path} · tools [{(m.tools ?? []).join(", ") || "none"}]
          {m.guardrail ? ` · 🛡️ ${m.guardrail}` : ""}
        </p>
      )}
    </div>
  );
}
