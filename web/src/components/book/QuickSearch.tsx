"use client";

import { useRouter } from "next/navigation";
import { useEffect, useState, type FormEvent } from "react";
import { addDays, loadTemporal } from "@/lib/dates";

export type PropertyLite = { property_code: string; property_name: string; city: string; state: string };

export function useProperties() {
  const [props, setProps] = useState<PropertyLite[]>([]);
  const [today, setToday] = useState<string | null>(null);
  useEffect(() => {
    fetch("/api/properties").then((r) => (r.ok ? r.json() : [])).then(setProps).catch(() => setProps([]));
    Promise.all([fetch("/api/health").then((r) => r.json()).catch(() => null), loadTemporal()]).then(([h]) =>
      setToday(h?.business_date ?? null),
    );
  }, []);
  return { props, today };
}

/** Landing-page search → /book with the query in the URL (shareable, back-button friendly). */
export function QuickSearch() {
  const router = useRouter();
  const { props, today } = useProperties();
  const submit = (e: FormEvent<HTMLFormElement>) => {
    e.preventDefault();
    const f = new FormData(e.currentTarget);
    router.push(`/book?${new URLSearchParams(Object.fromEntries(f) as Record<string, string>)}`);
  };
  const minIn = today ? addDays(today, 1) : undefined;
  return (
    <form onSubmit={submit} className="space-y-3">
      <div>
        <label className="label" htmlFor="qs-where">Destination</label>
        <select id="qs-where" name="where" className="input" required defaultValue="">
          <option value="" disabled>Choose a city</option>
          {props.map((p) => (
            <option key={p.property_code} value={p.property_code}>{p.city}, {p.state}</option>
          ))}
        </select>
      </div>
      <div className="grid grid-cols-2 gap-3">
        <div>
          <label className="label" htmlFor="qs-in">Check-in</label>
          <input id="qs-in" name="check_in" type="date" className="input" min={minIn} defaultValue={minIn ? addDays(minIn, 30) : undefined} required />
        </div>
        <div>
          <label className="label" htmlFor="qs-out">Check-out</label>
          <input id="qs-out" name="check_out" type="date" className="input" min={minIn} defaultValue={minIn ? addDays(minIn, 32) : undefined} required />
        </div>
      </div>
      <button className="btn btn-primary w-full" type="submit">See rooms &amp; rates</button>
      {today && <p className="text-xs text-muted">Inventory as of the PoC business date, {today}.</p>}
    </form>
  );
}
