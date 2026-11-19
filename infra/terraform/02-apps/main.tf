# Stage 2 — Vault configuration + application containers.
# Reads stage-1 outputs (network, Vault address/root token, Postgres admin) from local state.

terraform {
  required_version = ">= 1.6"
  required_providers {
    docker = { source = "kreuzwerker/docker", version = "4.7.0" }
    vault  = { source = "hashicorp/vault", version = "5.13.0" }
    random = { source = "hashicorp/random", version = "~> 3.7" }
  }
}

data "terraform_remote_state" "platform" {
  backend = "local"
  config = {
    path = "${path.module}/../01-platform/terraform.tfstate"
  }
}

locals {
  p         = data.terraform_remote_state.platform.outputs
  repo_root = abspath("${path.module}/../../..")
  # Rebuild the agent image whenever its sources, prompts, migrations or data change.
  agent_src_hash = sha1(join("", [
    for f in sort(concat(
      tolist(fileset(local.repo_root, "agent-service/src/**/*.py")),
      tolist(fileset(local.repo_root, "agent-service/{pyproject.toml,uv.lock,Dockerfile}")),
      tolist(fileset(local.repo_root, "agents/*.md")),
      tolist(fileset(local.repo_root, "db/migrations/*.sql")),
      tolist(fileset(local.repo_root, "solstice-data/*")),
    )) : filesha1("${local.repo_root}/${f}")
  ]))
}

provider "docker" {
  host = var.docker_host
}

# Terraform is the only holder of the root token, and only for configuration. Apps get AppRoles.
provider "vault" {
  address          = local.p.vault_addr
  token            = local.p.vault_root_token
  skip_child_token = true
}
