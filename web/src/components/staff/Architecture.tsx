"use client";

import { useEffect, useState, useSyncExternalStore } from "react";
import { DIAGRAMS } from "@/lib/diagrams";
import { Spinner } from "@/components/ui";

const DARK = "(prefers-color-scheme: dark)";
// modern-web-guidance (dark-mode): JS reading prefers-color-scheme must also handle its `change` event.
const subscribeScheme = (cb: () => void) => {
  const mq = matchMedia(DARK);
  mq.addEventListener("change", cb);
  return () => mq.removeEventListener("change", cb);
};

/** Renders the mermaid diagrams client-side, re-rendering when the OS color scheme changes. */
export function Architecture() {
  const [svgs, setSvgs] = useState<Record<string, string>>({});
  const dark = useSyncExternalStore(subscribeScheme, () => matchMedia(DARK).matches, () => false);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      const mermaid = (await import("mermaid")).default;
      mermaid.initialize({ startOnLoad: false, securityLevel: "strict", theme: dark ? "dark" : "neutral", fontFamily: "inherit" });
      const out: Record<string, string> = {};
      for (const d of DIAGRAMS) {
        const { svg } = await mermaid.render(`mmd-${d.id}-${dark ? "d" : "l"}`, d.code);
        out[d.id] = svg;
      }
      if (!cancelled) setSvgs(out);
    })();
    return () => {
      cancelled = true;
    };
  }, [dark]);

  return (
    <div className="space-y-6">
      {DIAGRAMS.map((d) => (
        <figure key={d.id} className="card p-5" aria-labelledby={`fig-${d.id}`}>
          <h2 id={`fig-${d.id}`} className="text-xl font-semibold">{d.title}</h2>
          <figcaption className="mb-4 mt-1 text-sm text-muted">{d.caption}</figcaption>
          {svgs[d.id] ? (
            <div className="overflow-x-auto [&_svg]:mx-auto [&_svg]:h-auto [&_svg]:max-w-full" role="img" aria-label={`${d.title} diagram`}
              dangerouslySetInnerHTML={{ __html: svgs[d.id] }} />
          ) : (
            <div className="flex items-center gap-2 text-sm text-muted"><Spinner label="Rendering diagram" /> Rendering…</div>
          )}
          <details className="mt-3 text-xs">
            <summary className="cursor-pointer text-muted">Mermaid source</summary>
            <pre className="mt-2 overflow-x-auto rounded-lg bg-sunken p-3">{d.code}</pre>
          </details>
        </figure>
      ))}
    </div>
  );
}
