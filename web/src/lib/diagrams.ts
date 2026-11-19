/**
 * Single source of truth for architecture diagrams (mermaid).
 * Rendered live at /staff/architecture and exported to docs/architecture-diagrams.md by
 * `node web/scripts/export-diagrams.ts`.
 */
export type Diagram = { id: string; title: string; caption: string; code: string };

export const DIAGRAMS: Diagram[] = [
  {
    id: "future-state",
    title: "Future-state production architecture (GCP)",
    caption:
      "Guest and reservation data stays in the systems of record (PMS, CRS, loyalty); the agent reads it through an integration layer and never writes to the PMS folio directly. Every box has a degraded mode: see the next diagram.",
    code: `flowchart LR
  subgraph Guests["Guests & staff"]
    G["Guest web / mobile"]
    S["Front desk & sales<br/>(SSO: Entra ID)"]
  end
  subgraph Edge["Edge"]
    LB["Cloud Load Balancer<br/>+ Cloud Armor WAF"]
  end
  subgraph App["Cloud Run · private VPC"]
    WEB["Next.js BFF<br/>sessions, PCI-free checkout"]
    AG["Agent service<br/>Google ADK · FastAPI<br/>min instances = 2"]
    WF["Group workflow workers<br/>ADK Workflow · Pub/Sub push"]
  end
  subgraph Model["Model serving"]
    GPU["Gemma 4 E2B<br/>Cloud Run GPU (L4) · vLLM<br/>min instances = 1, warm prefix"]
    FB["Fallback model<br/>Gemma 4 E4B / Vertex AI"]
  end
  subgraph Data["Data plane"]
    SQL[("Cloud SQL Postgres HA<br/>core · ops · agent schemas")]
    CACHE[("Memorystore<br/>sessions · rate cache")]
    BQ[("BigQuery<br/>funnel · evals · audit")]
  end
  subgraph SoR["Systems of record"]
    PMS["PMS<br/>Oracle OPERA Cloud (OHIP)"]
    CRS["CRS<br/>Sabre SynXis"]
    CRM["Loyalty / CRM"]
    PAY["Payment provider<br/>hosted fields + tokens"]
    TIX["Service desk<br/>cases & SLAs"]
  end
  subgraph Sec["Security & ops"]
    V["HashiCorp Vault (HA, KMS auto-unseal)<br/>dynamic DB creds · AppRole/GCP auth"]
    OBS["Cloud Monitoring · Trace · Logging<br/>OpenTelemetry from ADK"]
    PG["PagerDuty / on-call"]
  end
  INT["Integration layer<br/>Pub/Sub events + CDC<br/>idempotent adapters"]

  G --> LB --> WEB
  S --> LB
  WEB -->|"service token"| AG
  AG --> GPU
  AG -.->|"circuit open"| FB
  AG --> SQL
  AG --> CACHE
  WF --> SQL
  WF --> GPU
  INT <--> PMS
  INT <--> CRS
  INT <--> CRM
  INT --> SQL
  AG -->|"cases"| TIX
  WEB -->|"card data never<br/>reaches Solstice"| PAY
  AG -.->|"leases"| V
  WEB -.-> V
  AG -.-> OBS
  GPU -.-> OBS
  OBS --> PG
  SQL --> BQ`,
  },
  {
    id: "degradation",
    title: "Graceful degradation",
    caption:
      "The model is the least critical dependency. When it is slow or down, deterministic paths keep the guest moving, and nothing ever fails silently.",
    code: `flowchart TD
  M["Guest message"] --> R["Redact PII"]
  R --> T{"Safety / medical /<br/>legal triage"}
  T -->|"match"| E["Scripted reply +<br/>immediate hand-off<br/>(no LLM, ~5 ms)"]
  T -->|"no match"| H{"Model healthy?<br/>probe every 20 s"}
  H -->|"no"| D["Degraded mode:<br/>policy full-text search<br/>+ one-tap actions"]
  H -->|"yes"| A["ADK agent turn<br/>hard timeout"]
  A -->|"timeout / error"| D
  A --> G{"Output guardrails"}
  G -->|"unverified figure /<br/>staff-note leak"| F["Safe fallback reply<br/>+ offer hand-off"]
  G -->|"pass"| OK["Reply + cards"]
  A -.->|"PMS / DB down"| Q["Tool returns<br/>'system unavailable':<br/>agent offers hand-off,<br/>never guesses"]`,
  },
  {
    id: "concierge-turn",
    title: "Concierge turn (sequence)",
    caption: "Thin LLM, thick tools: code owns identity, facts, numbers and permissions; the model chooses tools and phrases the answer.",
    code: `sequenceDiagram
  autonumber
  participant B as Browser
  participant W as Next.js BFF
  participant A as Agent service
  participant L as Gemma 4 E2B
  participant P as Postgres (agent schema)
  B->>W: POST message (cookie session)
  W->>A: SSE request + guest_id from signed cookie
  A->>A: redact PII · triage · intent router
  A->>L: prompt (static prefix cached) + tool schemas + hint
  L-->>A: function_call request_stay_change
  A->>P: masked views + SECURITY DEFINER functions
  P-->>A: policy decision (Platinum: 2 PM confirmed)
  A-->>B: status + card events (streamed)
  A->>L: tool result
  L-->>A: draft reply
  A->>A: after_model: figures grounded? notes leaked? PII?
  A-->>B: final message + latency/path
  A->>P: funnel + turn metrics`,
  },
  {
    id: "group-workflow",
    title: "Group booking workflow (ADK Workflow graph)",
    caption: "Deterministic nodes make every decision. The LLM only reads emails (verified against the text) and writes prose (verified number by number).",
    code: `flowchart LR
  S(("start")) --> I["intake"]
  I -->|"email"| X["extract<br/>LLM"]
  X --> RG["register<br/>verify numbers vs text"]
  RG --> EV
  I -->|"form"| EV["evaluate<br/>rules engine"]
  EV -->|"clarify"| CP["list questions"] --> CW["write email<br/>LLM"] --> FZ
  EV -->|"review"| RS["Booking Rescue<br/>alt dates · properties · split"] --> PP
  EV -->|"auto"| HB["hold rooms 72h"] --> PP["assemble facts"]
  PP --> PW["write cover note<br/>LLM"] --> FZ["finalize<br/>numeric grounding · save"]`,
  },
  {
    id: "data-boundaries",
    title: "Data & PII boundaries",
    caption: "Least privilege is enforced by Postgres roles, not by prompt instructions. Vault issues the agent a 1-hour database user that can only see masked views.",
    code: `flowchart LR
  subgraph core["core schema (raw PII)"]
    GU["guests<br/>email, phone"]
    RE["reservations<br/>card last4, internal notes"]
  end
  subgraph agent["agent schema"]
    VG["v_guests<br/>l***@example.com · ***-***-0148"]
    VR["v_reservations<br/>card_on_file: true"]
    FN["functions<br/>place_hold · verify_guest · search_policy"]
  end
  subgraph ops["ops schema"]
    INV["inventory_nights<br/>CHECK sold+held ≤ capacity"]
    CASES["escalations · requests<br/>proposals · metrics"]
  end
  GU --> VG
  RE --> VR
  FN --> INV
  AR(["v-approle-agent-*<br/>(Vault, 1h TTL)"]) -->|"SELECT"| agent
  AR -->|"INSERT"| CASES
  AR -.-x|"denied"| core
  SR(["v-approle-staff-*"]) -->|"SELECT (no card data)"| core
  SR --> CASES`,
  },
  {
    id: "local-stack",
    title: "PoC stack (Terraform · Docker)",
    caption: "What runs today: two Terraform stages, a Vault-first boot order, and migrations as a one-shot job.",
    code: `flowchart LR
  subgraph TF1["terraform 01-platform"]
    NET["docker network"]
    PGc[("postgres:18")]
    VA["vault (dev mode)"]
    OL["ollama · gemma4:e2b<br/>GPU container or host"]
  end
  subgraph TF2["terraform 02-apps"]
    VC["Vault config<br/>KV · database engine · AppRole · policies"]
    MG["migrate (one-shot)<br/>schema + validated CSV seed"]
    AS["agent-service<br/>vault_mode=dynamic"]
    WB["web (Next.js)"]
  end
  VC --> VA
  MG --> PGc
  AS --> PGc
  AS --> OL
  AS -.->|"AppRole login,<br/>dynamic creds"| VA
  WB -.->|"AppRole: session secret,<br/>service token"| VA
  WB --> AS`,
  },
];
