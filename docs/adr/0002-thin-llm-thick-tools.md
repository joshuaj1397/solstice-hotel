# ADR-0002: Thin LLM, thick tools

**Status:** accepted · **Phase:** architecture

## Context
Gemma 4 E2B has about 2B effective parameters. In the first probe it answered "what time is
check-in?" by asking for a reservation number instead of looking up the policy. The brief
requires that the agent *never* invent a policy, rate or availability.

## Options
1. **Thin LLM, thick tools:** the model routes intent and phrases answers; code computes
   every decision *(recommended)*
2. Full ReAct agent with all tools exposed
3. A cascade, with E2B for chat and gemma4:12b for hard turns

## Decision
Option 1. Pricing, ceilings (including seasonal caps), blackouts, capacity, lead times,
cancellation terms, service-recovery windows, comp authority, escalation routing and PII
masking are all deterministic (`rules/`). The group workflow is a graph whose decision
nodes are plain functions.

## Consequences
- Every answer is traceable to a policy number or a data row, and testable (64 tests,
  including the CSV answer key).
- The model can be swapped (E4B, Gemini, Claude) without re-validating business rules.
- The model still has to *choose* tools reliably, which led to the router and repair in ADR-0006.
- Option 3 is kept as the future fallback model behind a circuit breaker.
