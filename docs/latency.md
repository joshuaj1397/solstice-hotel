# Latency target, and why

## The targets

| Path | Target | Measured (RTX 5060 8 GB laptop GPU, Gemma 4 E2B Q4) |
|---|---|---|
| Concierge, single-intent turn, end to end | **p95 ≤ 2.5 s**, p50 ≤ 1 s | **p50 0.67 s · p95 0.77 s** (14 scripted turns, final run; A/B run: 0.68 / 0.91 s) |
| First visible feedback (tool status or answer) | **≤ 300 ms** | status event emitted as soon as the tool is chosen |
| Safety / medical / legal message → scripted reply + case | **≤ 50 ms**, independent of the model | **2–5 ms** |
| Degraded mode (model down) → policy answer | ≤ 500 ms | ~60 ms |
| Group proposal from the web form | **≤ 60 s p95** (today: ~2 days) | **≈ 0.8–1.1 s** (≈ 3 s when the LLM cover note misses the prompt cache) |
| Group proposal from a free-text email | ≤ 60 s p95 | **≈ 4 s** |

## Why 2.5 seconds

The number comes from what the guest is comparing us to, and from the work a turn has to do.

1. **The alternative is the phone queue.** A guest calling the desk or central reservations
   waits minutes. Chat only beats that if it feels conversational. Usability research
   puts the "flow" limit around 1 s and the "attention" limit around 10 s. Responses in the
   1–3 s range are acceptable *when progress is visible*, which is why the UI streams a
   status line ("Checking your cancellation terms…") the moment a tool is chosen.
2. **The work in a turn is fixed.** A tool-using turn needs two model calls (choose the
   tool, then phrase the result) plus a database call:

   | Step | Budget |
   |---|---|
   | Browser → BFF → agent (TLS, cookie verify) | 50 ms |
   | PII redaction, triage, intent router | 5 ms |
   | LLM call 1: tool selection (prefix-cached prompt) | 400 ms |
   | Tool: Postgres (masked view or locked inventory function) | 50 ms |
   | LLM call 2: grounded reply | 500 ms |
   | Output guardrails | 5 ms |
   | **Sum at p50** | **≈ 1.0 s** |
   | Headroom for queueing under load (×2.5) | **p95 2.5 s** |

3. **The model was chosen to fit the budget, not the other way round.** Gemma 4 E2B
   generates at ~200 tokens/s on a consumer GPU. A 70B-class model on the same
   hardware would blow the budget on prefill alone. We pay for the small model with
   deterministic tools, a router and guardrails ([ADR-0002](adr/0002-thin-llm-thick-tools.md)).

## What we learned measuring it

| Change | Effect |
|---|---|
| Thinking **off** + intent router (vs thinking on, no router) | p50 3.1 s → **0.68 s**; correct tool 10/12 → **12/12** ([ADR-0006](adr/0006-model-configuration.md)) |
| Dynamic context (`{today}`, `{guest}`) moved to the **end** of the system prompt | Ollama's prefix cache covers rules + tool schemas: uncached prefill 2.8 s vs cached 0.3 s |
| **Prefix warm-up** at startup (one throwaway turn through the real path) | First guest of the day: 7 s → 0.6 s |
| `num_ctx` raised from Ollama's default 4096 to 16384 | Correctness, not speed: 4096 would silently truncate the system prompt on long conversations |
| `keep_alive=24h` + health-probe warm-up | Avoids the 20 s cold model load |

**Known gaps (and the production fix):**

- **Compound requests** ("late checkout *and* a suite?") make two tool calls and three LLM
  calls: 3–6 s. That's acceptable, but it's over the single-intent target. Parallel tool
  calls are the next optimization.
- **Shared prompt cache.** On one local Ollama slot, the group workflow's writer and the
  concierge evict each other's cached prefix: a turn right after a group run costs 2–3 s.
  In production the two workloads run on separate model replicas, and vLLM's automatic
  prefix caching holds many prefixes at once.

## How it's measured in production

Every turn writes `ops.turn_metrics` (latency, path `llm` / `triage_bypass` / `degraded`,
tools, model). `/staff/metrics` shows p50/p95 by path and flags p95 against the target. In
the future-state architecture the same numbers go to Cloud Monitoring via OpenTelemetry.
The SLO is p95 ≤ 2.5 s over 28 days, and the alert fires on a 1-hour burn rate. Before
scaling out: load-test (k6) at the expected evening peak, then set GPU replica count and
min-instances from measured tokens/s under continuous batching, not from guesses.
