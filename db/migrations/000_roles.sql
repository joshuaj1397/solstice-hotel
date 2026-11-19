-- 000_roles.sql — group roles (NOLOGIN). Login identities are issued by Vault
-- (dynamic credentials) or created by Terraform; they inherit one of these.
--
--   solstice_owner  owns every schema/object; SECURITY DEFINER functions run as it
--   solstice_agent  the LLM agent runtime: masked views + narrow write functions only
--   solstice_staff  staff console: full read except payment data, status updates on ops
DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'solstice_owner') THEN
    CREATE ROLE solstice_owner NOLOGIN;
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'solstice_agent') THEN
    CREATE ROLE solstice_agent NOLOGIN;
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'solstice_staff') THEN
    CREATE ROLE solstice_staff NOLOGIN;
  END IF;
END $$;

-- The migration runner must be able to SET ROLE solstice_owner.
GRANT solstice_owner TO CURRENT_USER;

DO $$
BEGIN
  EXECUTE format('GRANT CREATE, CONNECT ON DATABASE %I TO solstice_owner', current_database());
  EXECUTE format('GRANT CONNECT ON DATABASE %I TO solstice_agent, solstice_staff', current_database());
  EXECUTE format('REVOKE ALL ON DATABASE %I FROM PUBLIC', current_database());
END $$;

CREATE EXTENSION IF NOT EXISTS pgcrypto;
