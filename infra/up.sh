#!/usr/bin/env bash
# Bring up the Solstice local stack.
#   stage 1 (01-platform): network, Postgres, Vault (dev), Ollama (GPU) or host Ollama
#   stage 2 (02-apps):     Vault config (KV, dynamic DB creds, AppRoles) + migrate + agent-service [+ web]
#
# Override anything with TF_VAR_* env vars, e.g.
#   TF_VAR_agent_port=18080 TF_VAR_vault_port=18200 TF_VAR_enable_web=true ./infra/up.sh
set -euo pipefail
here="$(cd "$(dirname "$0")" && pwd)"

# Talk to the same Docker engine as the docker CLI (Docker Desktop's named pipe on Windows,
# ~/.docker/run/docker.sock on macOS, /var/run/docker.sock on Linux), unless the caller chose.
if [[ -z "${TF_VAR_docker_host:-}" ]]; then
  docker_host="$(docker context inspect --format '{{.Endpoints.docker.Host}}' 2>/dev/null || true)"
  if [[ -n "$docker_host" ]]; then export TF_VAR_docker_host="$docker_host"; fi
fi

# Ollama-in-a-container needs Docker GPU support (Docker Desktop WSL2 backend + NVIDIA driver).
# Fall back to the host's Ollama when it isn't available, unless the caller chose explicitly.
if [[ -z "${TF_VAR_ollama_mode:-}" ]]; then
  if [[ "$(uname -s)" == Darwin ]]; then
    # Docker Desktop on macOS has no GPU passthrough; the host's Ollama runs the model on Metal.
    echo "==> macOS: using host Ollama (TF_VAR_ollama_mode=host). Needs: ollama pull ${TF_VAR_model:-gemma4:e2b}" >&2
    export TF_VAR_ollama_mode=host
  elif docker run --rm --gpus all busybox true >/dev/null 2>&1; then
    export TF_VAR_ollama_mode=container
  else
    echo "!! Docker GPU passthrough unavailable -> using host Ollama (TF_VAR_ollama_mode=host)" >&2
    export TF_VAR_ollama_mode=host
  fi
fi

for stage in 01-platform 02-apps; do
  echo "==> terraform apply: $stage"
  terraform -chdir="$here/terraform/$stage" init -input=false >/dev/null
  terraform -chdir="$here/terraform/$stage" apply -input=false -auto-approve
done

echo
terraform -chdir="$here/terraform/02-apps" output
echo "Service token (local scripts):  terraform -chdir=infra/terraform/02-apps output -raw service_token"
