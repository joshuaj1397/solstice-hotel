# ADR-0009: Group booking as an ADK 2.x graph Workflow

**Status:** accepted · **Phase:** agents

## Context
ADK 2.14 (installed) adds `google.adk.workflow.Workflow`: nodes, routed edges, and LlmAgents
as nodes. The group process has three outcomes (clarify, review, auto) with different follow-ups.

## Decision
A `Workflow` graph ([group-workflow.md](../../agents/group-workflow.md)) where:
- decision nodes are plain functions that emit `Event(output=…, route=…)`;
- LLM nodes are `LlmAgent(output_schema=…)` that only extract (verified against the source
  text) or write prose (verified number by number);
- each node appends to a trace that the UI streams as a live pipeline.

## Consequences
- The branching logic is visible in code and in the UI, not buried in a prompt.
- If an LLM node fails or misbehaves, a template replaces its output: the workflow never
  blocks on the model.
- Runs in ~1 s for portal inquiries, versus about two days today.
