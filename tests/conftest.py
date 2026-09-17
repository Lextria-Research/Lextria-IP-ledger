"""Test fixtures: every test gets its own throwaway database.

backend.db resolves DB_PATH at import time, so the fixture repoints it at a
tmp_path before the schema is created. Without this, a test run would read and
write the developer's real backend/lextria.db.
"""

from contextlib import asynccontextmanager

import pytest
from starlette.testclient import TestClient

from backend import auth, db, main, roles


@pytest.fixture
def env(tmp_path, monkeypatch):
    """A signed-out TestClient against an empty, isolated ledger."""
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "test.db")
    db.init_db()
    auth.init_auth_schema()
    # The per-address rate limiter lives in module state shared by the whole
    # pytest process -- see auth.reset_ip_limiter.
    auth.reset_ip_limiter()

    # base_url matters: the default is http://testserver, and security.host_is_safe
    # rejects a registered domain name outright (that is the DNS-rebinding guard
    # doing its job). Real clients reach this server as localhost or by IP.
    with TestClient(app_without_lifespan(), base_url="http://localhost") as client:
        yield client


def app_without_lifespan():
    """The FastAPI app with its startup hook disabled.

    main.lifespan creates the superadmin and prints its key. Tests create the
    accounts they need explicitly, and running the hook would both add an
    account no test asked for and re-init the schema on the real DB_PATH before
    monkeypatch had a chance to apply.
    """
    main.app.router.lifespan_context = _noop_lifespan
    return main.app


@asynccontextmanager
async def _noop_lifespan(app):
    yield


@pytest.fixture
def accounts(env):
    """Create one account per role. Returns {role: (username, key)}.

    Depends on `env` so the database is already repointed at tmp_path before any
    account is written -- otherwise these would land in the real lextria.db.
    """
    made = {}
    for role, username in ((roles.SUPERADMIN, "boss"),
                          (roles.TRADEMARK_ADMIN, "tma"),
                          (roles.DRAFTER, "dee")):
        _user_id, key = auth.create_user(username, role)
        made[role] = (username, key)
    return made


def sign_in(client, username, key, **kwargs):
    """Sign in as `username` using their access key.

    `username` is accepted for readability at call sites and to keep existing
    test names meaningful, but the server identifies the account purely from
    the key -- there is no username in the request body.
    """
    return client.post("/api/login", json={"key": key}, **kwargs)
