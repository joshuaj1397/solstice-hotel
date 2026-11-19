"""Connection pools. Two identities, two pools:

agent  — used by the LLM-facing tools and the group workflow. Can only see `agent.*`
         (masked views + narrow functions). This is what "the agent can see" means.
staff  — used by the staff console endpoints (human users).
"""

from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager
from typing import Any, AsyncIterator

from psycopg import AsyncConnection
from psycopg.conninfo import make_conninfo
from psycopg.rows import dict_row
from psycopg_pool import AsyncConnectionPool

from . import secrets
from .config import Settings, get_settings

log = logging.getLogger(__name__)


class Database:
    def __init__(self, settings: Settings | None = None):
        self.s = settings or get_settings()
        self._agent: AsyncConnectionPool | None = None
        self._staff: AsyncConnectionPool | None = None
        self._secrets: secrets.ResolvedSecrets | None = None
        self._renew_task: asyncio.Task | None = None

    def _conninfo(self, cred: secrets.DbCredential, app: str) -> str:
        return make_conninfo(
            host=self.s.db_host, port=self.s.db_port, dbname=self.s.db_name,
            user=cred.user, password=cred.password, application_name=app,
        )

    async def _make_pool(self, cred: secrets.DbCredential, app: str, size: int) -> AsyncConnectionPool:
        pool = AsyncConnectionPool(
            self._conninfo(cred, app), min_size=1, max_size=size, open=False,
            kwargs={"row_factory": dict_row, "autocommit": True},
        )
        await pool.open(wait=True, timeout=15)
        return pool

    async def open(self) -> None:
        self._secrets = await asyncio.to_thread(secrets.resolve, self.s)
        self._agent = await self._make_pool(self._secrets.agent_db, "solstice-agent", 10)
        self._staff = await self._make_pool(self._secrets.staff_db, "solstice-staff", 5)
        if self.s.vault_mode == "dynamic":
            self._renew_task = asyncio.create_task(self._renew_loop())

    async def close(self) -> None:
        if self._renew_task:
            self._renew_task.cancel()
        for pool in (self._agent, self._staff):
            if pool:
                await pool.close()

    async def _renew_loop(self) -> None:
        """Keep dynamic Vault leases alive; swap pools if a lease is lost."""
        assert self._secrets
        while True:
            ttl = max(self._secrets.agent_db.lease_duration, 60)
            await asyncio.sleep(ttl / 2)
            for attr, role, app, size in (("agent_db", "solstice-agent", "solstice-agent", 10),
                                          ("staff_db", "solstice-staff", "solstice-staff", 5)):
                cred = getattr(self._secrets, attr)
                if await asyncio.to_thread(secrets.renew, self.s, cred):
                    continue
                new = await asyncio.to_thread(secrets.reissue, self.s, role)
                new_pool = await self._make_pool(new, app, size)
                old = self._agent if attr == "agent_db" else self._staff
                if attr == "agent_db":
                    self._agent = new_pool
                else:
                    self._staff = new_pool
                setattr(self._secrets, attr, new)
                if old:
                    await old.close()
                log.info("vault: rotated %s credentials → %s", role, new.user)

    @property
    def service_token(self) -> str | None:
        return self._secrets.service_token if self._secrets else None

    @asynccontextmanager
    async def agent_conn(self) -> AsyncIterator[AsyncConnection]:
        assert self._agent, "database not opened"
        async with self._agent.connection() as conn:
            yield conn

    @asynccontextmanager
    async def staff_conn(self) -> AsyncIterator[AsyncConnection]:
        assert self._staff, "database not opened"
        async with self._staff.connection() as conn:
            yield conn

    # --- small helpers -------------------------------------------------------
    async def fetch(self, sql: str, params: Any = None, *, staff: bool = False) -> list[dict]:
        ctx = self.staff_conn() if staff else self.agent_conn()
        async with ctx as conn:
            cur = await conn.execute(sql, params)
            return await cur.fetchall() if cur.description else []

    async def fetchrow(self, sql: str, params: Any = None, *, staff: bool = False) -> dict | None:
        rows = await self.fetch(sql, params, staff=staff)
        return rows[0] if rows else None

    async def ping(self) -> bool:
        try:
            await self.fetchrow("SELECT 1 AS ok")
            return True
        except Exception:  # noqa: BLE001
            return False


_db: Database | None = None


def get_db() -> Database:
    global _db
    if _db is None:
        _db = Database()
    return _db


def set_db(db: Database) -> None:
    global _db
    _db = db
