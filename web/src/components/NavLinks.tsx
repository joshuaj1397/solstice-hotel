"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

const NAV = [
  { href: "/stay", label: "My stay" },
  { href: "/book", label: "Book a stay" },
  { href: "/groups", label: "Groups & events" },
  { href: "/staff", label: "Staff" },
];

export function ActiveNav() {
  return <NavLinks path={usePathname()} />;
}

export function NavLinks({ path }: { path: string }) {
  return (
    <nav aria-label="Main" className="ms-auto flex gap-1 overflow-x-auto text-sm">
      {NAV.map((n) => {
        const active = path === n.href || path.startsWith(`${n.href}/`);
        return (
          <Link
            key={n.href}
            href={n.href}
            aria-current={active ? "page" : undefined}
            className={`whitespace-nowrap rounded-full px-3 py-1.5 font-medium transition-colors ${
              active ? "bg-ink text-paper" : "text-muted hover:bg-sunken hover:text-ink"
            }`}
          >
            {n.label}
          </Link>
        );
      })}
    </nav>
  );
}
