"""Runtime configuration. Non-secret settings come from env; secrets come from Vault."""

from __future__ import annotations

from datetime import date, datetime, time
from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict

REPO_ROOT = Path(__file__).resolve().parents[3]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="SOLSTICE_", env_file=".env", extra="ignore")

    # --- Postgres (credentials are resolved by secrets.py) ---
    db_host: str = "localhost"
    db_port: int = 5433
    db_name: str = "solstice"
    agent_db_user: str | None = None
    agent_db_password: str | None = None
    staff_db_user: str | None = None
    staff_db_password: str | None = None
    admin_db_user: str | None = None        # migrations only — never used by the API process
    admin_db_password: str | None = None

    # --- Vault ---
    # off     : read credentials from env (local unit tests only)
    # kv      : static secrets from KV v2
    # dynamic : short-lived Postgres users minted by Vault's database secrets engine
    vault_mode: Literal["off", "kv", "dynamic"] = "off"
    vault_addr: str = "http://localhost:8200"
    vault_token: str | None = None
    vault_role_id: str | None = None
    vault_secret_id: str | None = None
    vault_kv_mount: str = "secret"
    vault_kv_path: str = "solstice/agent-service"
    vault_db_mount: str = "database"

    # --- Model ---
    ollama_base_url: str = "http://localhost:11434"
    model: str = "gemma4:e2b"
    model_think: bool = False       # measured: same tool accuracy with the router, ~4x faster (docs/adr/0006)
    llm_timeout_s: float = 25.0
    keep_alive: str = "24h"          # keep the model resident; a cold load costs ~20 s
    num_ctx: int = 16384             # Ollama defaults to 4096 and silently truncates the system prompt

    # --- Business ---
    # The sample export is a snapshot from mid-July 2026 (last group inquiry: 2026-07-12).
    # Every policy clock (72h windows, lead times) runs against this date, not wall time.
    business_date: date = date(2026, 7, 12)
    business_time: time = time(12, 0)
    stay_hold_ttl_minutes: int = 15
    group_hold_ttl_hours: int = 72
    budget_match: bool = True        # offer the smallest in-authority discount that meets budget

    # --- Service ---
    service_token: str | None = None  # BFF → agent-service shared secret (from Vault in kv/dynamic)
    data_dir: Path = REPO_ROOT / "solstice-data"
    migrations_dir: Path = REPO_ROOT / "db" / "migrations"
    prompts_dir: Path = REPO_ROOT / "agents"
    cors_origins: list[str] = ["http://localhost:3000"]

    @property
    def business_now(self) -> datetime:
        return datetime.combine(self.business_date, self.business_time)

    @property
    def model_id(self) -> str:
        return f"ollama_chat/{self.model}"


@lru_cache
def get_settings() -> Settings:
    return Settings()
