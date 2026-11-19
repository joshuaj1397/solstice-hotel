variable "docker_host" {
  description = "Docker daemon endpoint (must match stage 1)."
  type        = string
  default     = "npipe:////./pipe/dockerDesktopLinuxEngine"
}

variable "agent_port" {
  description = "Host port (127.0.0.1 only) for the agent service API."
  type        = number
  default     = 8080
}

variable "web_port" {
  description = "Host port (127.0.0.1 only) for the Next.js app."
  type        = number
  default     = 3000
}

variable "enable_web" {
  description = "Build and run the Next.js container."
  type        = bool
  default     = true
}

variable "db_cred_ttl_seconds" {
  description = "Default lease TTL for Vault-issued Postgres users (the service renews at TTL/2)."
  type        = number
  default     = 3600
}

variable "db_cred_max_ttl_seconds" {
  description = "Hard ceiling on a Postgres user's lifetime; afterwards the service re-issues."
  type        = number
  default     = 86400
}

variable "staff_passcode" {
  description = "Staff console passcode for the PoC. Empty = generate one (see `terraform output -raw staff_passcode`)."
  type        = string
  default     = ""
  sensitive   = true
}
