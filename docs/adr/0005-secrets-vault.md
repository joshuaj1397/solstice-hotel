# ADR-0005: Secrets in HashiCorp Vault with dynamic database credentials

**Status:** accepted · **Phase:** infrastructure (Vault added mid-build at the product owner's request)

## Options presented
- DB credentials: **dynamic** (Vault database engine, per-instance users, 1 h TTL)
  *(recommended, chosen)* vs static KV passwords.
- Vault server: **dev mode** locally *(recommended, chosen)* vs server mode with file
  storage and a manual unseal.

## Decision
- KV v2: `solstice/agent-service` {service_token}, `solstice/migrator` {admin creds},
  `solstice/web` {service_token, session_secret, staff_passcode}.
- Database engine roles `solstice-agent` and `solstice-staff`:
  `CREATE ROLE … VALID UNTIL … IN ROLE solstice_agent|solstice_staff`.
- AppRole per workload (agent-service, migrator, web), each with a least-privilege policy.
  The agent-service can't read migrator credentials (verified: `Forbidden`).
- The agent service renews leases at half-TTL and swaps its connection pools with fresh
  credentials if a lease is lost (`db.py`).

## Consequences
- No long-lived database password exists outside Vault and Terraform state. State is
  gitignored; production state lives in an encrypted remote backend.
- Dev mode loses configuration on container restart; `infra/up.sh` re-applies it.
  Production: Raft HA + cloud-KMS auto-unseal + GCP/Kubernetes auth instead of AppRole secret IDs.
