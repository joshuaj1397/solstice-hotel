"use client";
/* eslint-disable @typescript-eslint/no-explicit-any */

import { useRef, useState, type FormEvent } from "react";
import { readSse } from "@/lib/sse";
import { useProperties } from "@/components/book/QuickSearch";
import { Pipeline, PipelineLegend, type Step } from "./Pipeline";
import { ProposalView } from "./ProposalView";
import { Spinner } from "@/components/ui";

const SAMPLE_EMAIL = `Hi Solstice team,
We're planning our engineering offsite in Nashville from October 20 to October 22, 2026 and need 16 Standard King rooms.
We'd also like a meeting room for 40 people with a projector. Our budget is around $190 per room per night. Is a 10% group discount possible?
Thanks, Jordan Ellis (Northwind Robotics), jordan.ellis@northwindrobotics.com, 615-555-0199`;

export function GroupRequest() {
  const { props } = useProperties();
  const [mode, setMode] = useState<"form" | "email">("form");
  const [steps, setSteps] = useState<Step[]>([]);
  const [running, setRunning] = useState(false);
  const [result, setResult] = useState<any>(null);
  const [error, setError] = useState<string | null>(null);
  const resultRef = useRef<HTMLDivElement>(null);
  const formRef = useRef<HTMLFormElement>(null);

  const run = async (url: string, body: unknown) => {
    setSteps([]);
    setResult(null);
    setError(null);
    setRunning(true);
    try {
      const res = await fetch(url, { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify(body) });
      if (!res.ok) throw new Error((await res.json().catch(() => ({}))).message ?? "Request failed");
      for await (const ev of readSse(res)) {
        if (ev.event === "step") setSteps((s) => [...s, ev.data as Step]);
        else if (ev.event === "result") setResult(ev.data);
        else if (ev.event === "error") throw new Error((ev.data as any).message);
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : "Something went wrong.");
    } finally {
      setRunning(false);
      resultRef.current?.focus();
    }
  };

  const submitForm = (e: FormEvent<HTMLFormElement>) => {
    e.preventDefault();
    const f = Object.fromEntries(new FormData(e.currentTarget)) as Record<string, string>;
    const num = (k: string) => (f[k] ? Number(f[k]) : null);
    run("/api/group/request", {
      company_name: f.company_name, contact_name: f.contact_name, contact_email: f.contact_email,
      contact_phone: f.contact_phone || null, event_type: f.event_type, preferred_property_code: f.property,
      alternate_property_ok: f.alternate_ok === "on", arrival_date: f.arrival_date || null, departure_date: f.departure_date || null,
      rooms_requested: num("rooms"), room_type_preference: f.room_type || null, requested_discount_pct: num("discount"),
      stated_budget_per_night: num("budget"), meeting_space_needed: f.meeting === "on", meeting_capacity_needed: num("capacity"),
      special_requests: f.special_requests || null,
    });
  };

  const fillWedding = () => {
    const el = formRef.current!;
    const set = (n: string, v: string | boolean) => {
      const i = el.elements.namedItem(n) as HTMLInputElement;
      if (i.type === "checkbox") i.checked = Boolean(v);
      else i.value = String(v);
    };
    set("company_name", "Rivera–Okafor Wedding"); set("contact_name", "Dana Rivera"); set("contact_email", "dana@example.com");
    set("event_type", "Wedding Block"); set("property", "SOL-PVD"); set("arrival_date", "2026-09-11"); set("departure_date", "2026-09-13");
    set("rooms", "12"); set("room_type", "Standard King"); set("discount", "8"); set("budget", "150");
    set("special_requests", "Welcome bags at check-in, rooms near each other if possible");
  };

  return (
    <div className="grid gap-6 lg:grid-cols-12">
      <section className="card p-5 lg:col-span-5" aria-labelledby="req-title">
        <h2 id="req-title" className="text-2xl font-semibold">Tell us about your group</h2>
        <fieldset className="mt-4">
          <legend className="label">How would you like to send it?</legend>
          <div className="inline-flex rounded-full border border-line bg-sunken p-1 text-sm">
            {(["form", "email"] as const).map((m) => (
              <label key={m} className="cursor-pointer rounded-full px-4 py-1.5 font-semibold text-muted has-[:checked]:bg-surface has-[:checked]:text-ink has-[:checked]:shadow-sm">
                <input type="radio" name="mode" value={m} checked={mode === m} onChange={() => setMode(m)} className="sr-only" />
                {m === "form" ? "Quick form" : "Paste an email"}
              </label>
            ))}
          </div>
        </fieldset>

        {mode === "form" ? (
          <form ref={formRef} onSubmit={submitForm} className="mt-4 grid grid-cols-2 gap-3">
            <Field id="company_name" label="Organization" className="col-span-2" required autoComplete="organization" />
            <Field id="contact_name" label="Your name" required autoComplete="name" />
            <Field id="contact_email" label="Email" type="email" required autoComplete="email" />
            <Field id="contact_phone" label="Phone" type="tel" autoComplete="tel" />
            <div>
              <label className="label" htmlFor="event_type">Event type</label>
              <select id="event_type" name="event_type" className="input" defaultValue="Corporate Retreat">
                {["Corporate Retreat", "Conference", "Wedding Block", "Youth Sports Travel", "Youth Group Travel", "Reunion"].map((t) => <option key={t}>{t}</option>)}
              </select>
            </div>
            <div className="col-span-2">
              <label className="label" htmlFor="property">Hotel</label>
              <select id="property" name="property" className="input" required defaultValue="">
                <option value="" disabled>Choose a hotel</option>
                {props.map((p) => <option key={p.property_code} value={p.property_code}>{p.property_name}</option>)}
              </select>
              <label className="mt-1.5 flex items-center gap-2 text-sm"><input type="checkbox" name="alternate_ok" /> A nearby Solstice hotel is fine too</label>
            </div>
            <Field id="arrival_date" label="Arrival" type="date" required />
            <Field id="departure_date" label="Departure" type="date" required />
            <Field id="rooms" label="Rooms per night" type="number" min={1} max={300} required inputMode="numeric" />
            <div>
              <label className="label" htmlFor="room_type">Room type</label>
              <select id="room_type" name="room_type" className="input" defaultValue="Standard King">
                {["Standard King", "Standard Double", "Deluxe King", "Suite"].map((t) => <option key={t}>{t}</option>)}
              </select>
            </div>
            <Field id="discount" label="Requested discount %" type="number" min={0} max={50} step="0.5" inputMode="decimal" />
            <Field id="budget" label="Budget / room / night ($)" type="number" min={0} inputMode="decimal" />
            <div className="col-span-2 flex flex-wrap items-end gap-3">
              <label className="flex items-center gap-2 text-sm"><input type="checkbox" name="meeting" /> Meeting space</label>
              <Field id="capacity" label="Seats" type="number" min={1} inputMode="numeric" />
            </div>
            <div className="col-span-2">
              <label className="label" htmlFor="special_requests">Anything else?</label>
              <textarea id="special_requests" name="special_requests" rows={2} className="input" maxLength={1000} />
            </div>
            <div className="col-span-2 flex flex-wrap gap-2">
              <button type="submit" className="btn btn-primary" disabled={running}>{running ? <Spinner label="Building proposal" /> : "Get my proposal"}</button>
              <button type="button" className="btn btn-ghost" onClick={fillWedding}>Fill a sample wedding</button>
            </div>
          </form>
        ) : (
          <form
            className="mt-4 space-y-3"
            onSubmit={(e) => {
              e.preventDefault();
              run("/api/group/intake", { email: String(new FormData(e.currentTarget).get("email")) });
            }}
          >
            <div>
              <label className="label" htmlFor="email-body">Your request, in your own words</label>
              <textarea id="email-body" name="email" rows={10} className="input font-mono text-xs" required minLength={20} maxLength={8000} defaultValue={SAMPLE_EMAIL} />
            </div>
            <p className="text-xs text-muted">Contact details are removed before the AI reads your message. The AI&apos;s extracted numbers are checked against your text.</p>
            <button type="submit" className="btn btn-primary" disabled={running}>{running ? <Spinner label="Reading your request" /> : "Get my proposal"}</button>
          </form>
        )}
      </section>

      <section className="lg:col-span-7" aria-labelledby="res-title">
        <div className="card space-y-4 p-5" ref={resultRef} tabIndex={-1}>
          <div className="flex flex-wrap items-center gap-2">
            <h2 id="res-title" className="text-2xl font-semibold">Your proposal</h2>
            <span className="ms-auto"><PipelineLegend /></span>
          </div>
          {steps.length > 0 || running ? <Pipeline steps={steps} running={running} /> : <p className="text-sm text-muted">Submit your request and watch the agent assemble a priced proposal in about a second.</p>}
          {error && <p role="alert" className="rounded-lg bg-bad-soft p-3 text-sm text-bad">{error}</p>}
          {result && <ProposalView result={result} audience="client" />}
        </div>
      </section>
    </div>
  );
}

function Field({ id, label, className, ...rest }: { id: string; label: string; className?: string } & React.InputHTMLAttributes<HTMLInputElement>) {
  return (
    <div className={className}>
      <label className="label" htmlFor={id}>{label}</label>
      <input id={id} name={id} className="input" {...rest} />
    </div>
  );
}
