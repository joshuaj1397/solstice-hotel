# Architecture decision records

Decisions were presented as explicit choices at each phase of the build. The recommended
option was marked, and measurements were used where a decision could be measured.

| ADR | Phase | Decision | Chosen by |
|---|---|---|---|
| [0001](0001-agent-runtime.md) | Architecture | Python ADK agent service behind a Next.js BFF | product owner (recommended) |
| [0002](0002-thin-llm-thick-tools.md) | Architecture | Thin LLM, thick deterministic tools | product owner (recommended) |
| [0003](0003-reservation-frequency.md) | Architecture | "Reservation frequency" = conversion **and** overbooking safety; budget-match pricing | product owner (recommended) |
| [0004](0004-pii-least-privilege.md) | Data | Least-privilege Postgres roles, masked views, redaction, tokenized checkout | engineering |
| [0005](0005-secrets-vault.md) | Infra | HashiCorp Vault with dynamic Postgres credentials; dev mode locally | product owner (added Vault; chose dynamic + dev mode) |
| [0006](0006-model-configuration.md) | Agents | Gemma 4 E2B, thinking off + intent router + tool-call repair | measured A/B |
| [0007](0007-infrastructure-terraform-docker.md) | Infra | Terraform Docker-provider stack in two stages; Ollama GPU container with host fallback | product owner (chose Docker over the native-PG + GCP option) |
| [0008](0008-ui.md) | UI | Stay companion; Tailwind v4; modern-web-guidance; four surfaces | product owner |
| [0009](0009-group-workflow-graph.md) | Agents | ADK 2.x graph `Workflow` with verified LLM nodes | engineering |
