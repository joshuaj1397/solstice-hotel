"""Secret resolution via HashiCorp Vault.

Two production-shaped modes:
  kv       static credentials stored in KV v2 (written by Terraform)
  dynamic  Vault's database secrets engine mints a short-lived Postgres user per
           service instance; the lease is renewed in the background and the pool is
           rebuilt with fresh credentials if renewal fails.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

import hvac

from .config import Settings

log = logging.getLogger(__name__)


@dataclass
class DbCredential:
    user: str
    password: str
    lease_id: str | None = None
    lease_duration: int = 0


@dataclass
class ResolvedSecrets:
    agent_db: DbCredential
    staff_db: DbCredential
    service_token: str | None
    extra: dict = field(default_factory=dict)


def _client(s: Settings) -> hvac.Client:
    client = hvac.Client(url=s.vault_addr, token=s.vault_token)
    if not s.vault_token and s.vault_role_id and s.vault_secret_id:
        client.auth.approle.login(role_id=s.vault_role_id, secret_id=s.vault_secret_id)
    if not client.is_authenticated():
        raise RuntimeError("Vault authentication failed (set SOLSTICE_VAULT_TOKEN or AppRole ids)")
    return client


def _read_kv(client: hvac.Client, s: Settings) -> dict:
    resp = client.secrets.kv.v2.read_secret_version(
        mount_point=s.vault_kv_mount, path=s.vault_kv_path, raise_on_deleted_version=True
    )
    return resp["data"]["data"]


def _dynamic_cred(client: hvac.Client, s: Settings, role: str) -> DbCredential:
    resp = client.secrets.database.generate_credentials(name=role, mount_point=s.vault_db_mount)
    return DbCredential(
        user=resp["data"]["username"],
        password=resp["data"]["password"],
        lease_id=resp["lease_id"],
        lease_duration=resp["lease_duration"],
    )


def resolve(s: Settings) -> ResolvedSecrets:
    if s.vault_mode == "off":
        if not (s.agent_db_user and s.staff_db_user):
            raise RuntimeError("vault_mode=off requires SOLSTICE_AGENT_DB_USER / SOLSTICE_STAFF_DB_USER")
        return ResolvedSecrets(
            agent_db=DbCredential(s.agent_db_user, s.agent_db_password or ""),
            staff_db=DbCredential(s.staff_db_user, s.staff_db_password or ""),
            service_token=s.service_token,
        )

    client = _client(s)
    kv = _read_kv(client, s)
    if s.vault_mode == "kv":
        agent = DbCredential(kv["agent_db_user"], kv["agent_db_password"])
        staff = DbCredential(kv["staff_db_user"], kv["staff_db_password"])
    else:
        agent = _dynamic_cred(client, s, "solstice-agent")
        staff = _dynamic_cred(client, s, "solstice-staff")
        log.info("vault: issued dynamic db users %s / %s (ttl %ss)", agent.user, staff.user, agent.lease_duration)
    return ResolvedSecrets(agent_db=agent, staff_db=staff, service_token=kv.get("service_token"))


def renew(s: Settings, cred: DbCredential) -> bool:
    """Renew a dynamic lease. Returns False if the lease is gone and creds must be re-issued."""
    if s.vault_mode != "dynamic" or not cred.lease_id:
        return True
    try:
        _client(s).sys.renew_lease(lease_id=cred.lease_id)
        return True
    except Exception as exc:  # noqa: BLE001 — any failure means re-issue
        log.warning("vault: lease renewal failed for %s: %s", cred.user, exc)
        return False


def reissue(s: Settings, role: str) -> DbCredential:
    return _dynamic_cred(_client(s), s, role)


def admin_credentials(s: Settings) -> DbCredential:
    """Migration-only credentials (KV `solstice/migrator`), or env when Vault is off."""
    if s.vault_mode == "off":
        return DbCredential(s.admin_db_user or "postgres", s.admin_db_password or "")
    client = _client(s)
    data = client.secrets.kv.v2.read_secret_version(
        mount_point=s.vault_kv_mount, path="solstice/migrator", raise_on_deleted_version=True
    )["data"]["data"]
    return DbCredential(data["admin_db_user"], data["admin_db_password"])
