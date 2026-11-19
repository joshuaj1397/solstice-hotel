# ADR-0007: Terraform Docker-provider stack; Ollama GPU container with host fallback

**Status:** accepted, with one item constrained by the environment · **Phase:** infrastructure

## Options presented
1. Native Postgres via the `postgresql` provider + a GCP module validated but not applied *(recommended)*
2. **Docker local stack** (Postgres, Vault, Ollama, agent, web as containers) *(chosen)*
3. Deploy to a real GCP project

Ollama placement: **container with GPU** *(recommended, chosen)* vs host Ollama.

## Decision
Two Terraform roots:

- `01-platform`: network, volumes, Postgres, Vault, Ollama.
- `02-apps`: Vault configuration via the Vault provider, which needs a running Vault; a
  one-shot migrate job; the agent service; web.

Images are built by Terraform from the repo. All ports bind to 127.0.0.1. Postgres isn't
published at all.

## Environment constraint
On the development laptop, Docker Desktop runs the **Hyper-V** engine, and NVIDIA GPU
passthrough requires the **WSL2** engine (`nvidia-container-cli: libnvidia-ml.so.1 not found`).
The GPU container is fully coded (`gpus = "all"`, read-only mount of `~/.ollama/models`, no
host port). `up.sh` / `up.ps1` detect GPU support and fall back to `ollama_mode=host`
(containers call `host.docker.internal:11434`). Switching Docker Desktop to the WSL2 engine
enables the container path with no code change.

## Consequences
- One command reproduces the PoC. A re-apply is a no-op (verified).
- The future-state GCP architecture is documented ([architecture.md](../architecture.md)) but
  not provisioned; the service code is already container- and Vault-ready for Cloud Run.
