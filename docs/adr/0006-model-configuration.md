# ADR-0006: Gemma 4 E2B with thinking off, an intent router, and tool-call repair

**Status:** accepted · **Phase:** agents · **Decided by measurement**

## Context
Gemma 4 E2B supports tools and an optional thinking mode. Fourteen scripted guest turns
(12 scored for correct tool use) were run under four configurations.

| Variant | Correct tool | p50 | p95 | Notable failure |
|---|---|---|---|---|
| Thinking on, no router | 10/12 | 3.1 s | 5.2 s | "I am submitting this as a dispute…" with no tool call |
| Thinking off, no router | 6/12 | 0.6 s | 4.6 s | Made up "case number [Case Number]" |
| Thinking on + router | 12/12 | 2.8 s | 3.8 s | — |
| **Thinking off + router** | **12/12** | **0.68 s** | **0.91 s** | — |

## Decision
- `think=false`, temperature 0.2.
- **Intent router** (`rules/intent.py`): regex intent detection with arguments parsed in code;
  a one-line hint is appended to the instruction for that turn.
- **Tool-call repair** (`after_model_callback`): if the model answers without calling the
  routed tool, its reply is replaced with that function call, once per turn.
- **Say–do guard:** a reply that claims an action ("I have submitted…", "case number") with
  no tool call this turn is replaced.
- `num_ctx=16384` (Ollama's 4096 default silently truncates the system prompt),
  `keep_alive=24h`, dynamic context placed at the *end* of the prompt (prefix caching), and a
  prompt-prefix warm-up at startup.

## Consequences
- 4× faster at equal or better tool accuracy; latency target met ([latency.md](../latency.md)).
- The router is deliberately conservative: it only hints on unambiguous asks, and open
  questions ("rooms in Austin…?") are left to the model.
- New intents need a regex and a unit test (`tests/test_intent.py`).
