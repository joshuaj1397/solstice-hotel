output "agent_url" {
  value = "http://localhost:${var.agent_port}"
}

output "web_url" {
  value = var.enable_web ? "http://localhost:${var.web_port}" : "(web disabled)"
}

output "vault_ui" {
  value = "${local.p.vault_addr}/ui"
}

output "service_token" {
  description = "BFF→agent-service shared secret (also in Vault KV). For local scripts only."
  value       = random_password.service_token.result
  sensitive   = true
}

output "staff_passcode" {
  description = "Staff console passcode (PoC only; stored in Vault KV solstice/web)."
  value       = var.staff_passcode != "" ? var.staff_passcode : random_password.staff_passcode.result
  sensitive   = true
}

output "migrate_logs" {
  value = docker_container.migrate.container_logs
}
