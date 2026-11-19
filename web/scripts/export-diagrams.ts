// Exports the app's mermaid diagrams to docs/architecture-diagrams.md (Node 23.6+ runs .ts natively).
//   node web/scripts/export-diagrams.ts
import { writeFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { DIAGRAMS } from "../src/lib/diagrams.ts";

const out = resolve(dirname(fileURLToPath(import.meta.url)), "../../docs/architecture-diagrams.md");
const body = [
  "# Architecture diagrams",
  "",
  "> Generated from `web/src/lib/diagrams.ts` (the same source the staff console renders at `/staff/architecture`).",
  "> Edit the TypeScript, then run `node web/scripts/export-diagrams.ts`.",
  "",
  ...DIAGRAMS.flatMap((d) => [`## ${d.title}`, "", d.caption, "", "```mermaid", d.code, "```", ""]),
].join("\n");
writeFileSync(out, body, "utf8");
console.log(`wrote ${out} (${DIAGRAMS.length} diagrams)`);
