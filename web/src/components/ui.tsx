"use client";

import { useEffect, useState, type ReactNode } from "react";
import { formatDate, loadTemporal } from "@/lib/dates";

/** Indeterminate spinner on a native <progress> so assistive tech announces busy state. */
export function Spinner({ label = "Loading" }: { label?: string }) {
  return <progress className="spinner" aria-label={label} />;
}

/** Calendar date rendered with Temporal.PlainDate (polyfilled on demand). */
export function PlainDate({ iso, weekday, year }: { iso?: string | null; weekday?: boolean; year?: boolean }) {
  const [, setReady] = useState(0);
  useEffect(() => {
    loadTemporal().then(() => setReady(1));
  }, []);
  if (!iso) return <span>—</span>;
  return <time dateTime={iso.slice(0, 10)}>{formatDate(iso, { weekday, year })}</time>;
}

export function useTemporalReady(): boolean {
  const [ready, setReady] = useState(false);
  useEffect(() => {
    loadTemporal().then(() => setReady(true));
  }, []);
  return ready;
}

const TONE: Record<string, string> = {
  ok: "bg-ok-soft text-ok",
  warn: "bg-warn-soft text-warn",
  bad: "bg-bad-soft text-bad",
  sun: "bg-sun-soft text-sun",
  dusk: "bg-dusk-soft text-dusk",
  muted: "bg-sunken text-muted",
};

export function Chip({ tone = "muted", children }: { tone?: keyof typeof TONE; children: ReactNode }) {
  return <span className={`chip ${TONE[tone]}`}>{children}</span>;
}

export function TierBadge({ tier }: { tier?: string }) {
  const tone = tier === "Platinum" ? "dusk" : tier === "Gold" ? "sun" : tier === "Silver" ? "muted" : "muted";
  return <Chip tone={tone}>{tier && tier !== "None" ? `★ ${tier}` : "Guest"}</Chip>;
}

export function statusTone(status?: string): keyof typeof TONE {
  switch (status) {
    case "confirmed":
    case "approved":
    case "auto_approved":
    case "resolved":
    case "sent":
    case "Confirmed":
    case "Checked-in":
      return "ok";
    case "pending_desk":
    case "needs_review":
    case "acknowledged":
    case "same_day":
      return "warn";
    case "declined":
    case "immediate":
    case "Cancelled":
    case "No-show":
      return "bad";
    case "needs_clarification":
    case "open":
      return "dusk";
    default:
      return "muted";
  }
}

export function humanize(s?: string | null): string {
  if (!s) return "";
  return s.replaceAll("_", " ").replace(/^\w/, (c) => c.toUpperCase());
}

export function EmptyState({ title, children }: { title: string; children?: ReactNode }) {
  return (
    <div className="rounded-2xl border border-dashed border-line p-6 text-center text-sm text-muted">
      <p className="font-semibold text-ink">{title}</p>
      {children}
    </div>
  );
}
