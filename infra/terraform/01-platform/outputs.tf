output "network_name" {
  value = docker_network.solstice.name
}

output "postgres_host" {
  description = "Hostname of Postgres on the private network."
  value       = "postgres"
}

output "postgres_db" {
  value = var.postgres_db
}

output "postgres_admin_user" {
  value = var.postgres_admin_user
}

output "postgres_admin_password" {
  value     = random_password.postgres_admin.result
  sensitive = true
}

output "vault_addr" {
  description = "Vault address as seen from the host (used by the stage-2 Vault provider)."
  value       = "http://127.0.0.1:${var.vault_port}"
}

output "vault_addr_internal" {
  description = "Vault address as seen from containers on the private network."
  value       = "http://vault:8200"
}

output "vault_root_token" {
  description = "Dev-mode root token. Used only by Terraform to configure Vault; never given to an app."
  value       = random_password.vault_root_token.result
  sensitive   = true
}

output "ollama_mode" {
  value = var.ollama_mode
}

output "ollama_base_url" {
  description = "Ollama URL as seen from application containers."
  value       = var.ollama_mode == "container" ? "http://ollama:11434" : "http://host.docker.internal:11434"
}

output "model" {
  value = var.model
}
