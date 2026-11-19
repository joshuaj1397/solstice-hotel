"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useState, type FormEvent, type ReactNode } from "react";
import { Spinner } from "@/components/ui";

const NAV = [
  { href: "/staff", label: "Queue" },
  { href: "/staff/groups", label: "Group sales" },
  { href: "/staff/metrics", label: "Metrics" },
  { href: "/staff/architecture", label: "Architecture" },
];

export function StaffGate({ children }: { children: ReactNode }) {
  const path = usePathname();
  const [who, setWho] = useState<string | null | undefined>(undefined);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    fetch("/api/staff/session").then(async (r) => setWho(r.ok ? (await r.json()).staff : null)).catch(() => setWho(null));
  }, []);

  const signIn = async (e: FormEvent<HTMLFormElement>) => {
    e.preventDefault();
    const f = new FormData(e.currentTarget);
    const r = await fetch("/api/staff/session", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ name: f.get("name"), passcode: f.get("passcode") }),
    });
    if (!r.ok) return setError("Incorrect passcode.");
    setWho(String(f.get("name") || "Front Desk"));
  };

  if (who === undefined) return <div className="p-10"><Spinner label="Checking staff session" /></div>;
  if (who === null) {
    return (
      <div className="mx-auto max-w-sm px-4 py-16">
        <p className="eyebrow">Solstice staff</p>
        <h1 className="text-3xl font-semibold">Team console</h1>
        <p className="mb-5 mt-2 text-sm text-muted">Proof of concept sign-in. Production uses the hotel&apos;s SSO (Entra ID / Okta) with role-based access.</p>
        <form onSubmit={signIn} className="card space-y-3 p-5">
          <div>
            <label className="label" htmlFor="staff-name">Your name &amp; role</label>
            <input id="staff-name" name="name" className="input" defaultValue="Renee (Front Desk)" autoComplete="name" required />
          </div>
          <div>
            <label className="label" htmlFor="staff-pass">Passcode</label>
            <input id="staff-pass" name="passcode" type="password" className="input" autoComplete="current-password" required />
            <p className="mt-1 text-xs text-muted">
              Local dev: <code>solstice-staff</code>. Docker stack: <code>terraform -chdir=infra/terraform/02-apps output -raw staff_passcode</code>
            </p>
          </div>
          {error && <p role="alert" className="text-sm text-bad">{error}</p>}
          <button type="submit" className="btn btn-dusk w-full">Sign in</button>
        </form>
      </div>
    );
  }

  return (
    <div className="mx-auto max-w-7xl px-4 py-6 sm:px-6">
      <div className="mb-6 flex flex-wrap items-center gap-3">
        <div>
          <p className="eyebrow">Team console · signed in as {who}</p>
          <h1 className="text-3xl font-semibold">Solstice operations</h1>
        </div>
        <nav aria-label="Staff" className="ms-auto flex gap-1 rounded-full border border-line bg-surface p-1 text-sm">
          {NAV.map((n) => {
            const active = n.href === "/staff" ? path === "/staff" || path.startsWith("/staff/cases") : path.startsWith(n.href);
            return (
              <Link key={n.href} href={n.href} aria-current={active ? "page" : undefined}
                className={`rounded-full px-3 py-1.5 font-medium ${active ? "bg-dusk text-on-accent" : "text-muted hover:text-ink"}`}>
                {n.label}
              </Link>
            );
          })}
        </nav>
      </div>
      {children}
    </div>
  );
}
