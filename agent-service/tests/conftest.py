import asyncio
import sys

import pytest
import pytest_asyncio

from solstice_agents import services
from solstice_agents.db import Database, set_db


@pytest.fixture(scope="session")
def event_loop_policy():
    # psycopg's async driver can't run on Windows' default Proactor loop.
    if sys.platform == "win32":
        return asyncio.WindowsSelectorEventLoopPolicy()
    return asyncio.DefaultEventLoopPolicy()


@pytest.fixture(scope="session", autouse=True)
def fresh_seed():
    """Tests assert against the sample data, so start from a clean reseed (wipes demo holds/cases)."""
    import psycopg

    from solstice_agents import migrate
    from solstice_agents.config import get_settings

    s = get_settings()
    with psycopg.connect(migrate._admin_conninfo(s)) as conn:
        migrate.apply_migrations(conn, s.migrations_dir)
        migrate.seed(conn, s, reseed=True)


@pytest_asyncio.fixture
async def db():
    d = Database()
    await d.open()
    set_db(d)
    services._catalog = None
    yield d
    await d.close()
