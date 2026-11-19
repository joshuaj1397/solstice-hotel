"use client";
/* eslint-disable @typescript-eslint/no-explicit-any */

import { useSearchParams, useRouter } from "next/navigation";
import { useEffect, useState, type FormEvent } from "react";
import { Concierge } from "@/components/concierge/Concierge";
import { CardView } from "@/components/concierge/Cards";
import { EmptyState, Spinner } from "@/components/ui";
import { nightsBetween } from "@/lib/dates";
import { useProperties } from "./QuickSearch";

export function BookStay() {
  const params = useSearchParams();
  const router = useRouter();
  const { props } = useProperties();
  const where = params.get("where") ?? "";
  const checkIn = params.get("check_in") ?? "";
  const checkOut = params.get("check_out") ?? "";
  const key = where && checkIn && checkOut ? `${where}|${checkIn}|${checkOut}` : null;
  const [fetched, setFetched] = useState<{ key: string; data: any } | null>(null);

  useEffect(() => {
    if (!key) return;
    let alive = true;
    fetch(`/api/availability?${new URLSearchParams({ where, check_in: checkIn, check_out: checkOut })}`)
      .then((r) => r.json())
      .catch(() => ({ found: false, message: "Availability is temporarily unavailable." }))
      .then((data) => alive && setFetched({ key, data }));
    return () => {
      alive = false;
    };
  }, [key, where, checkIn, checkOut]);
  // Loading is derived, not stored: we're loading whenever the fetched result is for a different query.
  const loading = key !== null && fetched?.key !== key;
  const result = fetched?.key === key ? fetched.data : null;

  const submit = (e: FormEvent<HTMLFormElement>) => {
    e.preventDefault();
    const f = new FormData(e.currentTarget);
    router.replace(`/book?${new URLSearchParams(Object.fromEntries(f) as Record<string, string>)}`);
  };
  const nights = nightsBetween(checkIn, checkOut);

  return (
    <div className="mx-auto grid max-w-7xl gap-6 px-4 py-6 sm:px-6 lg:grid-cols-12">
      <div className="space-y-4 lg:col-span-5">
        <div>
          <p className="eyebrow">Book a stay</p>
          <h1 className="text-3xl font-semibold">Rooms &amp; rates</h1>
        </div>
        <form onSubmit={submit} className="card grid grid-cols-2 gap-3 p-4" key={`${where}${checkIn}${checkOut}`}>
          <div className="col-span-2">
            <label className="label" htmlFor="b-where">Destination</label>
            <select id="b-where" name="where" className="input" defaultValue={where} required>
              <option value="" disabled>Choose a city</option>
              {props.map((p) => (
                <option key={p.property_code} value={p.property_code}>{p.property_name} · {p.city}</option>
              ))}
            </select>
          </div>
          <div>
            <label className="label" htmlFor="b-in">Check-in</label>
            <input id="b-in" name="check_in" type="date" className="input" defaultValue={checkIn} required />
          </div>
          <div>
            <label className="label" htmlFor="b-out">Check-out</label>
            <input id="b-out" name="check_out" type="date" className="input" defaultValue={checkOut} required />
          </div>
          <button type="submit" className="btn btn-primary col-span-2">
            Search{nights ? ` · ${nights} night${nights === 1 ? "" : "s"}` : ""}
          </button>
        </form>
        {loading ? (
          <div className="flex items-center gap-2 text-muted"><Spinner label="Checking availability" /> Checking live availability…</div>
        ) : result ? (
          <CardView kind="check_availability" data={result} onAsk={() => {}} sessionId={null} internals={false} />
        ) : (
          <EmptyState title="Pick a destination and dates">or just ask Sol: &ldquo;Which hotel suits a 3-night family trip in August?&rdquo;</EmptyState>
        )}
      </div>
      <div className="lg:col-span-7 lg:sticky lg:top-20 lg:self-start">
        <Concierge
          greeting="Hi! I'm Sol. I can check live availability across all Solstice hotels, explain our policies, and hold a room for you while you decide. Where are you headed?"
          prompts={["Rooms in Austin Sept 18–20, 2026?", "Do you allow pets?", "What's your cancellation policy?", "Which hotel has the biggest meeting space?"]}
        />
      </div>
    </div>
  );
}
