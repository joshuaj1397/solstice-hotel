variable "docker_host" {
  description = "Docker daemon endpoint, e.g. npipe:////./pipe/dockerDesktopLinuxEngine (Docker Desktop, Windows), unix://$HOME/.docker/run/docker.sock (Docker Desktop, macOS), unix:///var/run/docker.sock (Linux). Null = DOCKER_HOST or the provider default; the up/down scripts pass the active docker context's endpoint."
  type        = string
  default     = null
}

variable "project" {
  type    = string
  default = "solstice"
}

variable "vault_port" {
  description = "Host port (127.0.0.1 only) for the Vault API/UI."
  type        = number
  default     = 8200
}

variable "postgres_image" {
  type    = string
  default = "postgres:18"
}

variable "postgres_db" {
  type    = string
  default = "solstice"
}

variable "postgres_admin_user" {
  type    = string
  default = "postgres"
}

variable "vault_image" {
  type    = string
  default = "hashicorp/vault:2.2.1"
}

variable "ollama_mode" {
  description = "\"container\" runs Ollama with the GPU inside the stack; \"host\" uses the host's Ollama via host.docker.internal."
  type        = string
  default     = "container"
  validation {
    condition     = contains(["container", "host"], var.ollama_mode)
    error_message = "ollama_mode must be \"container\" or \"host\"."
  }
}

variable "ollama_image" {
  type    = string
  default = "ollama/ollama:0.40.13"
}

variable "ollama_models_dir" {
  description = "Host directory holding the Ollama model cache (mounted read-only). Empty = ~/.ollama/models."
  type        = string
  default     = ""
}

variable "ollama_context_length" {
  description = "Server-side default context. The agent also sends num_ctx explicitly."
  type        = number
  default     = 16384
}

variable "model" {
  type    = string
  default = "gemma4:e2b"
}
