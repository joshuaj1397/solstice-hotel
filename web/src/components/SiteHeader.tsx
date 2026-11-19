import Link from "next/link";
import { Suspense } from "react";
import { ActiveNav, NavLinks } from "./NavLinks";

/** Static shell (prerendered); only the active-link highlight depends on the URL, so it streams in. */
export function SiteHeader() {
  return (
    <header className="sticky top-0 z-20 border-b border-line bg-paper/85 backdrop-blur">
      <div className="mx-auto flex max-w-7xl items-center gap-6 px-4 py-3 sm:px-6">
        <Link href="/" className="flex items-center gap-2" aria-label="Solstice Hotel Group home">
          <span aria-hidden className="grid size-8 place-items-center rounded-full bg-sun text-on-accent">
            <svg viewBox="0 0 24 24" className="size-5" fill="currentColor"><circle cx="12" cy="12" r="5" /><path d="M12 1v3M12 20v3M1 12h3M20 12h3M4.2 4.2l2.1 2.1M17.7 17.7l2.1 2.1M4.2 19.8l2.1-2.1M17.7 6.3l2.1-2.1" stroke="currentColor" strokeWidth="2" strokeLinecap="round" /></svg>
          </span>
          <span className="font-display text-xl font-semibold tracking-tight">Solstice</span>
        </Link>
        <Suspense fallback={<NavLinks path="" />}>
          <ActiveNav />
        </Suspense>
      </div>
    </header>
  );
}
