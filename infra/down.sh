#!/usr/bin/env bash
# Tear down the Solstice local stack (apps first, then platform). Removes the Postgres volume.
# Use the same TF_VAR_* values you brought it up with.
set -euo pipefail
here="$(cd "$(dirname "$0")" && pwd)"
if [[ -z "${TF_VAR_docker_host:-}" ]]; then
  docker_host="$(docker context inspect --format '{{.Endpoints.docker.Host}}' 2>/dev/null || true)"
  if [[ -n "$docker_host" ]]; then export TF_VAR_docker_host="$docker_host"; fi
fi
export TF_VAR_ollama_mode="${TF_VAR_ollama_mode:-$(terraform -chdir="$here/terraform/01-platform" output -raw ollama_mode 2>/dev/null || echo container)}"

for stage in 02-apps 01-platform; do
  if [[ -f "$here/terraform/$stage/terraform.tfstate" ]]; then
    echo "==> terraform destroy: $stage"
    terraform -chdir="$here/terraform/$stage" destroy -input=false -auto-approve
  fi
done
