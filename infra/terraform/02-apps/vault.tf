# ---------------------------------------------------------------------------------------
# Vault layout
#
#   secret/ (KV v2, mounted by dev mode)
#     solstice/agent-service  { service_token }                  ← agent-service AppRole
#     solstice/migrator       { admin_db_user, admin_db_password } ← migrator AppRole only
#     solstice/web            { service_token, session_secret, staff_passcode }  ← web AppRole
#   database/ (database secrets engine, PostgreSQL plugin)
#     roles/solstice-agent  → short-lived LOGIN user ∈ group role solstice_agent
#     roles/solstice-staff  → short-lived LOGIN user ∈ group role solstice_staff
#   auth/approle/
#     role/agent-service, role/migrator, role/web   (one least-privilege policy each)
# ---------------------------------------------------------------------------------------

resource "random_password" "service_token" {
  length  = 48
  special = false
}

resource "random_password" "session_secret" {
  length  = 64
  special = false
}

# --- KV v2 secrets -----------------------------------------------------------------------
resource "vault_kv_secret_v2" "agent_service" {
  mount     = "secret"
  name      = "solstice/agent-service"
  data_json = jsonencode({ service_token = random_password.service_token.result })
}

resource "vault_kv_secret_v2" "migrator" {
  mount = "secret"
  name  = "solstice/migrator"
  data_json = jsonencode({
    admin_db_user     = local.p.postgres_admin_user
    admin_db_password = local.p.postgres_admin_password
  })
}

resource "random_password" "staff_passcode" {
  length  = 20
  special = false
}

resource "vault_kv_secret_v2" "web" {
  mount = "secret"
  name  = "solstice/web"
  data_json = jsonencode({
    service_token  = random_password.service_token.result
    session_secret = random_password.session_secret.result
    # PoC staff console passcode. Production replaces this with SSO (Entra ID / Okta) + RBAC.
    staff_passcode = var.staff_passcode != "" ? var.staff_passcode : random_password.staff_passcode.result
  })
}

# --- Dynamic Postgres credentials ---------------------------------------------------------
resource "vault_mount" "database" {
  path        = "database"
  type        = "database"
  description = "Dynamic, short-lived Postgres credentials for Solstice services"
}

resource "vault_database_secret_backend_connection" "postgres" {
  backend           = vault_mount.database.path
  name              = "solstice-postgres"
  allowed_roles     = ["solstice-agent", "solstice-staff"]
  verify_connection = true

  postgresql {
    connection_url = "postgresql://{{username}}:{{password}}@${local.p.postgres_host}:5432/${local.p.postgres_db}?sslmode=disable"
    username       = local.p.postgres_admin_user
    password       = local.p.postgres_admin_password
  }
}

locals {
  db_roles = {
    "solstice-agent" = "solstice_agent" # LLM-facing runtime: masked agent.* surface only
    "solstice-staff" = "solstice_staff" # staff console: full read minus payment data
  }
}

resource "vault_database_secret_backend_role" "app" {
  for_each = local.db_roles
  backend  = vault_mount.database.path
  name     = each.key
  db_name  = vault_database_secret_backend_connection.postgres.name
  creation_statements = [
    "CREATE ROLE \"{{name}}\" WITH LOGIN PASSWORD '{{password}}' VALID UNTIL '{{expiration}}' INHERIT;",
    "GRANT ${each.value} TO \"{{name}}\";",
  ]
  revocation_statements = [
    "REVOKE ${each.value} FROM \"{{name}}\";",
    "DROP ROLE IF EXISTS \"{{name}}\";",
  ]
  default_ttl = var.db_cred_ttl_seconds
  max_ttl     = var.db_cred_max_ttl_seconds
}

# --- Policies (least privilege per workload) ------------------------------------------
resource "vault_policy" "agent_service" {
  name   = "solstice-agent-service"
  policy = <<-EOT
    path "secret/data/solstice/agent-service" { capabilities = ["read"] }
    path "database/creds/solstice-agent"      { capabilities = ["read"] }
    path "database/creds/solstice-staff"      { capabilities = ["read"] }
    path "sys/leases/renew"                   { capabilities = ["update"] }
  EOT
}

resource "vault_policy" "migrator" {
  name   = "solstice-migrator"
  policy = <<-EOT
    path "secret/data/solstice/migrator" { capabilities = ["read"] }
  EOT
}

resource "vault_policy" "web" {
  name   = "solstice-web"
  policy = <<-EOT
    path "secret/data/solstice/web" { capabilities = ["read"] }
  EOT
}

# --- AppRole auth ------------------------------------------------------------------------
resource "vault_auth_backend" "approle" {
  type = "approle"
}

locals {
  approles = {
    "agent-service" = vault_policy.agent_service.name
    "migrator"      = vault_policy.migrator.name
    "web"           = vault_policy.web.name
  }
}

resource "vault_approle_auth_backend_role" "app" {
  for_each       = local.approles
  backend        = vault_auth_backend.approle.path
  role_name      = each.key
  token_policies = [each.value]
  token_ttl      = 3600
  token_max_ttl  = 14400
}

# Local-stack shortcut: the secret_id is handed to the container as an env var. In production
# the workload authenticates with platform identity (GCP/AWS/K8s auth) or a response-wrapped
# secret_id delivered by the orchestrator — see infra/README.md.
resource "vault_approle_auth_backend_role_secret_id" "app" {
  for_each  = local.approles
  backend   = vault_auth_backend.approle.path
  role_name = vault_approle_auth_backend_role.app[each.key].role_name
}
