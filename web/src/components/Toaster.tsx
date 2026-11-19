"use client";

import { useEffect, useRef, useState } from "react";

/**
 * Toasts per modern-web-guidance (persistent-toast-notifications):
 * popover="manual" (no light dismiss), one consistent named region, announced via
 * ariaNotify() with an aria-live fallback, explicit Close button, no focus stealing.
 * Anything in a toast is also visible elsewhere in the UI (cards, queues), so nothing
 * is lost when it times out.
 */
type Toast = { id: number; text: string; tone: "ok" | "warn" | "bad" | "info" };

export function toast(text: string, tone: Toast["tone"] = "info") {
  window.dispatchEvent(new CustomEvent("sol-toast", { detail: { text, tone } }));
}

export function Toaster() {
  const [items, setItems] = useState<Toast[]>([]);
  const live = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!Object.hasOwn(HTMLElement.prototype, "popover")) {
      import("@oddbird/popover-polyfill").catch(() => undefined); // only when native popover is missing
    }
    const onToast = (e: Event) => {
      const { text, tone } = (e as CustomEvent).detail;
      const id = Date.now() + Math.random();
      setItems((xs) => [...xs.slice(-2), { id, text, tone }]);
      const doc = document as Document & { ariaNotify?: (msg: string) => void };
      if (typeof doc.ariaNotify === "function") doc.ariaNotify(text);
      else if (live.current) live.current.textContent = text;
      setTimeout(() => setItems((xs) => xs.filter((t) => t.id !== id)), 6000);
    };
    window.addEventListener("sol-toast", onToast);
    return () => window.removeEventListener("sol-toast", onToast);
  }, []);

  return (
    <div role="region" aria-label="Notifications">
      <div ref={live} aria-live="polite" className="sr-only" />
      {items.map((t, i) => (
        <ToastItem key={t.id} toast={t} offset={i} onClose={() => setItems((xs) => xs.filter((x) => x.id !== t.id))} />
      ))}
    </div>
  );
}

function ToastItem({ toast: t, offset, onClose }: { toast: Toast; offset: number; onClose: () => void }) {
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const el = ref.current as (HTMLDivElement & { showPopover?: () => void }) | null;
    el?.showPopover?.();
  }, []);
  const dot = { ok: "bg-ok", warn: "bg-warn", bad: "bg-bad", info: "bg-dusk" }[t.tone];
  return (
    <div
      ref={ref}
      {...({ popover: "manual" } as Record<string, string>)}
      className="toast"
      style={{ insetBlockEnd: `${1 + offset * 4.25}rem` }}
    >
      <div className="flex items-start gap-3">
        <span aria-hidden className={`mt-1.5 size-2 shrink-0 rounded-full ${dot}`} />
        <p className="text-sm">{t.text}</p>
        <button type="button" onClick={onClose} className="ms-auto text-xs font-semibold text-muted hover:text-ink">
          Close
        </button>
      </div>
    </div>
  );
}
