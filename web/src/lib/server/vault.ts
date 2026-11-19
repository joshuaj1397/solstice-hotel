import "server-only";

/**
 * Web-tier secrets (session signing key, agent-service token, staff passcode).
 *
 * In the Docker stack these come from Vault KV `secret/solstice/web` via AppRole
 * (VAULT_ADDR + VAULT_ROLE_ID + VAULT_SECRET_ID). For local `next dev` without Vault
 * they fall back to env vars. Values are fetched once and cached in memory.
 */
export type WebSecrets = {
  sessionSecret: string;
  serviceToken: string | null;
  staffPasscode: string;
};

let cached: Promise<WebSecrets> | null = null;

async function fromVault(): Promise<WebSecrets> {
  const addr = process.env.VAULT_ADDR!;
  const login = await fetch(`${addr}/v1/auth/approle/login`, {
    method: "POST",
    body: JSON.stringify({ role_id: process.env.VAULT_ROLE_ID, secret_id: process.env.VAULT_SECRET_ID }),
    cache: "no-store",
  });
  if (!login.ok) throw new Error(`vault login failed: ${login.status}`);
  const token = (await login.json()).auth.client_token as string;
  const mount = process.env.VAULT_KV_MOUNT ?? "secret";
  const path = process.env.VAULT_KV_PATH ?? "solstice/web";
  const res = await fetch(`${addr}/v1/${mount}/data/${path}`, { headers: { "X-Vault-Token": token }, cache: "no-store" });
  if (!res.ok) throw new Error(`vault read failed: ${res.status}`);
  const data = (await res.json()).data.data as Record<string, string>;
  return {
    sessionSecret: data.session_secret,
    serviceToken: data.service_token ?? null,
    staffPasscode: data.staff_passcode ?? process.env.STAFF_PASSCODE ?? "solstice-staff",
  };
}

function fromEnv(): WebSecrets {
  return {
    sessionSecret: process.env.SESSION_SECRET ?? "dev-only-insecure-session-secret-change-me-0123456789",
    serviceToken: process.env.AGENT_SERVICE_TOKEN ?? null,
    staffPasscode: process.env.STAFF_PASSCODE ?? "solstice-staff",
  };
}

export function secrets(): Promise<WebSecrets> {
  if (!cached) {
    cached = (process.env.VAULT_ADDR && process.env.VAULT_ROLE_ID ? fromVault() : Promise.resolve(fromEnv())).catch(
      (err) => {
        cached = null; // retry on next request instead of caching the failure
        throw err;
      },
    );
  }
  return cached;
}
