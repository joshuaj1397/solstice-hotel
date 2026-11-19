/**
 * Calendar dates are location-agnostic: "2026-08-22" is the same night everywhere.
 * Per modern-web-guidance (capture-location-agnostic-data) we use Temporal.PlainDate,
 * never `new Date("2026-08-22")` (which shifts a day west of UTC). Native Temporal is
 * used when present; otherwise the polyfill is loaded on demand.
 */
import type { Temporal as TemporalNS } from "temporal-polyfill";

type TemporalT = typeof TemporalNS;
let T: TemporalT | null = (globalThis as { Temporal?: TemporalT }).Temporal ?? null;
let loading: Promise<TemporalT> | null = null;

export function loadTemporal(): Promise<TemporalT> {
  if (T) return Promise.resolve(T);
  loading ??= import("temporal-polyfill").then((m) => (T = m.Temporal));
  return loading;
}

export function temporalReady(): TemporalT | null {
  return T;
}

const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

/** Formats an ISO calendar date. Falls back to a pure string transform until Temporal is loaded. */
export function formatDate(iso: string | null | undefined, opts: { weekday?: boolean; year?: boolean } = {}): string {
  if (!iso) return "—";
  const day = iso.slice(0, 10);
  if (T) {
    const d = T.PlainDate.from(day);
    return d.toLocaleString("en-US", {
      month: "short",
      day: "numeric",
      ...(opts.year === false ? {} : { year: "numeric" }),
      ...(opts.weekday ? { weekday: "short" } : {}),
    });
  }
  const [y, m, d] = day.split("-").map(Number);
  return `${MONTHS[m - 1]} ${d}${opts.year === false ? "" : `, ${y}`}`;
}

export function nightsBetween(checkIn: string, checkOut: string): number | null {
  if (!T || !checkIn || !checkOut) return null;
  const n = T.PlainDate.from(checkIn).until(T.PlainDate.from(checkOut), { largestUnit: "day" }).days;
  return n > 0 ? n : null;
}

export function addDays(iso: string, days: number): string {
  if (!T) return iso;
  return T.PlainDate.from(iso).add({ days }).toString();
}

export function money(n: number | null | undefined, cents = true): string {
  if (n == null) return "—";
  return n.toLocaleString("en-US", { style: "currency", currency: "USD", maximumFractionDigits: cents ? 2 : 0 });
}

export function formatTimestamp(iso: string | null | undefined): string {
  if (!iso) return "—";
  if (T) {
    try {
      return T.Instant.from(iso.endsWith("Z") || /[+-]\d\d:\d\d$/.test(iso) ? iso : `${iso}Z`)
        .toLocaleString("en-US", { month: "short", day: "numeric", hour: "numeric", minute: "2-digit" });
    } catch {
      /* fall through */
    }
  }
  return iso.replace("T", " ").slice(0, 16);
}
