# ADR-0001: Agent runtime as a Python ADK service behind a Next.js BFF

**Status:** accepted · **Phase:** architecture

## Context
The stack is mandated as Next.js (TypeScript) + Google ADK + a local Gemma 4 E2B. ADK's
most mature SDK is Python, and its documented path to local models is `LiteLlm` → Ollama.
The TypeScript ADK's non-Gemini model support is thinner.

## Options
1. **Python ADK service (FastAPI)**, with Next.js as UI + backend-for-frontend *(recommended)*
2. ADK TypeScript inside Next.js route handlers (one language, one deploy)

## Decision
Option 1. Next.js route handlers are the only thing the browser talks to. They hold the
signed session cookie and a Vault-sourced service token, and stream the agent's SSE through.

## Consequences
- The agent service maps directly to Cloud Run or Vertex AI Agent Engine later, and scales
  independently of the web tier.
- Two languages. The contract between them is a small JSON/SSE API (`/v1/*`).
- The agent service isn't internet-facing; guest identity is asserted by the BFF and
  re-checked against session ownership in the agent.
