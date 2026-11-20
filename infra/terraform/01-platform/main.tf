# Stage 1 — platform: network, Postgres, Vault (dev mode), Ollama (GPU).
# Stage 2 (../02-apps) configures Vault and runs the application containers; it reads this
# stage's outputs through terraform_remote_state, because the Vault provider can only be
# configured once Vault is up.

terraform {
  required_version = ">= 1.6"
  required_providers {
    docker = { source = "kreuzwerker/docker", version = "4.7.0" }
    random = { source = "hashicorp/random", version = "~> 3.7" }
  }
}

provider "docker" {
  host = var.docker_host
}

locals {
  labels = { "com.solstice.stack" = var.project, "com.solstice.stage" = "platform" }
  # Forward slashes so a Windows home (C:\Users\...) stays a valid Docker bind-mount path.
  ollama_models_dir = var.ollama_models_dir != "" ? var.ollama_models_dir : replace(pathexpand("~/.ollama/models"), "\\", "/")
}

# --- secrets generated once, handed to Vault in stage 2 ---------------------------------
resource "random_password" "postgres_admin" {
  length  = 32
  special = false
}

resource "random_password" "vault_root_token" {
  length  = 32
  special = false
}

# --- network & storage ------------------------------------------------------------------
resource "docker_network" "solstice" {
  name   = "${var.project}-net"
  driver = "bridge"
}

resource "docker_volume" "pgdata" {
  name = "${var.project}-pgdata"
}

# --- images (kept locally on destroy so re-ups are fast) --------------------------------
resource "docker_image" "postgres" {
  name         = var.postgres_image
  keep_locally = true
}

resource "docker_image" "vault" {
  name         = var.vault_image
  keep_locally = true
}

resource "docker_image" "ollama" {
  count        = var.ollama_mode == "container" ? 1 : 0
  name         = var.ollama_image
  keep_locally = true
}

# --- Postgres: system of record + ops state. Not published to the host. ----------------
resource "docker_container" "postgres" {
  name    = "${var.project}-postgres"
  image   = docker_image.postgres.image_id
  restart = "unless-stopped"
  env = [
    "POSTGRES_USER=${var.postgres_admin_user}",
    "POSTGRES_PASSWORD=${random_password.postgres_admin.result}",
    "POSTGRES_DB=${var.postgres_db}",
  ]
  volumes {
    volume_name    = docker_volume.pgdata.name
    container_path = "/var/lib/postgresql"
  }
  networks_advanced {
    name    = docker_network.solstice.name
    aliases = ["postgres"]
  }
  healthcheck {
    test         = ["CMD-SHELL", "pg_isready -U ${var.postgres_admin_user} -d ${var.postgres_db}"]
    interval     = "5s"
    timeout      = "3s"
    retries      = 20
    start_period = "5s"
  }
  wait         = true
  wait_timeout = 120
  labels {
    label = "com.solstice.stack"
    value = var.project
  }
}

# --- Vault (dev mode: in-memory, auto-unsealed). Stage 2 rebuilds all config each apply.
resource "docker_container" "vault" {
  name    = "${var.project}-vault"
  image   = docker_image.vault.image_id
  restart = "unless-stopped"
  command = ["server", "-dev"]
  env = [
    "VAULT_DEV_ROOT_TOKEN_ID=${random_password.vault_root_token.result}",
    "VAULT_DEV_LISTEN_ADDRESS=0.0.0.0:8200",
    "VAULT_ADDR=http://127.0.0.1:8200",
  ]
  capabilities {
    add = ["CAP_IPC_LOCK"] # the daemon reports the CAP_ form; using it avoids a perpetual diff
  }
  ports {
    internal = 8200
    external = var.vault_port
    ip       = "127.0.0.1"
  }
  networks_advanced {
    name    = docker_network.solstice.name
    aliases = ["vault"]
  }
  healthcheck {
    test     = ["CMD", "vault", "status", "-address=http://127.0.0.1:8200"]
    interval = "3s"
    timeout  = "3s"
    retries  = 20
  }
  wait         = true
  wait_timeout = 90
  labels {
    label = "com.solstice.stack"
    value = var.project
  }
}

# --- Ollama serving Gemma 4 E2B on the GPU. Private network only (no host port). -------
# The host's model cache is mounted read-only so the 4.6 GB model isn't re-downloaded and
# the container can never prune or modify the host's models.
resource "docker_container" "ollama" {
  count   = var.ollama_mode == "container" ? 1 : 0
  name    = "${var.project}-ollama"
  image   = docker_image.ollama[0].image_id
  restart = "unless-stopped"
  gpus    = "all"
  env = [
    "OLLAMA_HOST=0.0.0.0:11434",
    "OLLAMA_KEEP_ALIVE=24h",
    "OLLAMA_NOPRUNE=1",
    "OLLAMA_CONTEXT_LENGTH=${var.ollama_context_length}",
  ]
  volumes {
    host_path      = local.ollama_models_dir
    container_path = "/root/.ollama/models"
    read_only      = true
  }
  networks_advanced {
    name    = docker_network.solstice.name
    aliases = ["ollama"]
  }
  healthcheck {
    test         = ["CMD", "ollama", "list"]
    interval     = "5s"
    timeout      = "5s"
    retries      = 30
    start_period = "5s"
  }
  wait         = true
  wait_timeout = 180
  labels {
    label = "com.solstice.stack"
    value = var.project
  }
}
