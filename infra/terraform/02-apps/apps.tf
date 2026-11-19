# ---------------------------------------------------------------------------------------
# Application containers
# ---------------------------------------------------------------------------------------

locals {
  db_env = [
    "SOLSTICE_DB_HOST=${local.p.postgres_host}",
    "SOLSTICE_DB_PORT=5432",
    "SOLSTICE_DB_NAME=${local.p.postgres_db}",
  ]
  vault_env = [
    "SOLSTICE_VAULT_ADDR=${local.p.vault_addr_internal}",
  ]
}

resource "docker_image" "agent" {
  name         = "solstice/agent-service:local"
  keep_locally = true
  build {
    context    = local.repo_root
    dockerfile = "agent-service/Dockerfile"
  }
  triggers = {
    src = local.agent_src_hash
  }
}

# --- One-shot migration job: schema + validated CSV seed. Uses the admin credential from
# KV (migrator AppRole); the API process never sees it. Terraform waits for it to exit 0.
resource "docker_container" "migrate" {
  name     = "solstice-migrate"
  image    = docker_image.agent.image_id
  command  = ["solstice-migrate"]
  must_run = false
  attach   = true
  logs     = true
  env = concat(local.db_env, local.vault_env, [
    "SOLSTICE_VAULT_MODE=kv",
    "SOLSTICE_VAULT_ROLE_ID=${vault_approle_auth_backend_role.app["migrator"].role_id}",
    "SOLSTICE_VAULT_SECRET_ID=${vault_approle_auth_backend_role_secret_id.app["migrator"].secret_id}",
  ])
  networks_advanced {
    name = local.p.network_name
  }
  labels {
    label = "com.solstice.stack"
    value = "solstice"
  }
  depends_on = [vault_kv_secret_v2.migrator]

  lifecycle {
    postcondition {
      condition     = self.exit_code == 0
      error_message = "solstice-migrate failed; see `docker logs solstice-migrate`."
    }
  }
}

# --- Agent service: dynamic DB users from Vault, Gemma via Ollama. -----------------------
resource "docker_container" "agent" {
  name    = "solstice-agent-service"
  image   = docker_image.agent.image_id
  restart = "unless-stopped"
  env = concat(local.db_env, local.vault_env, [
    "SOLSTICE_VAULT_MODE=dynamic",
    "SOLSTICE_VAULT_ROLE_ID=${vault_approle_auth_backend_role.app["agent-service"].role_id}",
    "SOLSTICE_VAULT_SECRET_ID=${vault_approle_auth_backend_role_secret_id.app["agent-service"].secret_id}",
    "SOLSTICE_OLLAMA_BASE_URL=${local.p.ollama_base_url}",
    "SOLSTICE_MODEL=${local.p.model}",
    "SOLSTICE_CORS_ORIGINS=[\"http://localhost:${var.web_port}\"]",
  ])
  ports {
    internal = 8080
    external = var.agent_port
    ip       = "127.0.0.1"
  }
  networks_advanced {
    name    = local.p.network_name
    aliases = ["agent-service"]
  }
  host {
    host = "host.docker.internal"
    ip   = "host-gateway"
  }
  healthcheck {
    test         = ["CMD", "python", "-c", "import sys,urllib.request; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8080/health', timeout=4).status == 200 else 1)"]
    interval     = "10s"
    timeout      = "5s"
    retries      = 12
    start_period = "20s"
  }
  wait         = true
  wait_timeout = 240
  labels {
    label = "com.solstice.stack"
    value = "solstice"
  }
  depends_on = [
    docker_container.migrate,
    vault_database_secret_backend_role.app,
    vault_kv_secret_v2.agent_service,
  ]
}

# --- Web (Next.js BFF + UI). Off by default until web/ is built. -------------------------
resource "docker_image" "web" {
  count        = var.enable_web ? 1 : 0
  name         = "solstice/web:local"
  keep_locally = true
  build {
    context    = "${local.repo_root}/web"
    dockerfile = "Dockerfile"
  }
  triggers = {
    src = sha1(join("", [
      for f in sort(tolist(fileset("${local.repo_root}/web", "{src,app,public,lib,components}/**"))) :
      filesha1("${local.repo_root}/web/${f}")
    ]))
    pkg = fileexists("${local.repo_root}/web/package.json") ? filesha1("${local.repo_root}/web/package.json") : ""
  }
}

resource "docker_container" "web" {
  count   = var.enable_web ? 1 : 0
  name    = "solstice-web"
  image   = docker_image.web[0].image_id
  restart = "unless-stopped"
  env = [
    "AGENT_URL=http://agent-service:8080",
    "VAULT_ADDR=${local.p.vault_addr_internal}",
    "VAULT_ROLE_ID=${vault_approle_auth_backend_role.app["web"].role_id}",
    "VAULT_SECRET_ID=${vault_approle_auth_backend_role_secret_id.app["web"].secret_id}",
    "INSECURE_COOKIES=1", # local stack is plain HTTP on 127.0.0.1; production terminates TLS at the LB
  ]
  ports {
    internal = 3000
    external = var.web_port
    ip       = "127.0.0.1"
  }
  networks_advanced {
    name    = local.p.network_name
    aliases = ["web"]
  }
  wait         = true
  wait_timeout = 120
  labels {
    label = "com.solstice.stack"
    value = "solstice"
  }
  depends_on = [docker_container.agent, vault_kv_secret_v2.web]
}
