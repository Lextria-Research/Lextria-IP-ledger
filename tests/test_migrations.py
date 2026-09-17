"""Alembic migrations against a throwaway database.

Two things matter here that a plain schema test would not catch: that
`alembic upgrade head` alone produces a database the app can actually run
against (nothing here depends on the app having initialised it first), and
that the two independent ways a database can come into being -- Alembic
first, or the app's own CREATE TABLE IF NOT EXISTS first -- land on the same
schema. See alembic/versions/5d06663f5855_*.py for why both paths exist.
"""

import sqlite3
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config

from backend import auth, db

REPO_ROOT = Path(__file__).resolve().parent.parent


def _alembic_config():
    """An in-process Config pointed at this repo's alembic.ini.

    alembic/env.py resolves its target database by importing
    backend.db.DB_PATH at the moment each command runs (not at process start),
    so calling command.upgrade()/command.stamp() AFTER monkeypatching
    db.DB_PATH -- as every test below does -- is what makes these commands
    land on the throwaway file rather than the real backend/lextria.db.
    """
    cfg = Config(str(REPO_ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", str(REPO_ROOT / "alembic"))
    return cfg


@pytest.fixture
def alembic_db(tmp_path, monkeypatch):
    """Point backend.db.DB_PATH (and therefore alembic/env.py) at a throwaway
    file for the duration of one test."""
    target = tmp_path / "alembic_test.db"
    monkeypatch.setattr(db, "DB_PATH", target)
    return target


def _table_columns(sqlite_path, table):
    conn = sqlite3.connect(sqlite_path)
    try:
        return [r[1] for r in conn.execute("PRAGMA table_info(%s)" % table)]
    finally:
        conn.close()


def _table_names(sqlite_path):
    conn = sqlite3.connect(sqlite_path)
    try:
        rows = conn.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table' "
            "AND name NOT LIKE 'sqlite_%'"
        )
        return {r[0] for r in rows}
    finally:
        conn.close()


def _index_names(sqlite_path):
    conn = sqlite3.connect(sqlite_path)
    try:
        rows = conn.execute(
            "SELECT name FROM sqlite_master WHERE type = 'index' "
            "AND name NOT LIKE 'sqlite_%'"
        )
        return {r[0] for r in rows}
    finally:
        conn.close()


EXPECTED_TABLES = {
    "alembic_version", "ledger_state", "ledger_history",
    "users", "sessions", "login_history",
}


def test_alembic_env_points_at_backend_db_path():
    """env.py must resolve the same DB_PATH the app uses, not a second,
    hardcoded path that could silently drift out of sync with it."""
    env_source = (REPO_ROOT / "alembic" / "env.py").read_text(encoding="utf-8")
    assert "from backend.db import DB_PATH" in env_source
    assert "sqlite:///" in env_source


class TestAlembicOnly:
    """`alembic upgrade head` against a database Python has never touched."""

    def test_upgrade_head_creates_every_table(self, alembic_db):
        command.upgrade(_alembic_config(), "head")
        assert alembic_db.exists()
        assert _table_names(alembic_db) == EXPECTED_TABLES

    def test_upgrade_head_creates_the_key_based_users_schema(self, alembic_db):
        command.upgrade(_alembic_config(), "head")
        columns = set(_table_columns(alembic_db, "users"))
        # The key-based columns must be present...
        assert {"key_hash", "key_hint", "key_issued_at"} <= columns
        # ...and there is no password column to have drifted back in.
        assert "password_hash" not in columns

    def test_upgrade_head_creates_expected_indexes(self, alembic_db):
        command.upgrade(_alembic_config(), "head")
        assert _index_names(alembic_db) == {"idx_sessions_user", "idx_history_at"}

    def test_no_login_attempts_table(self, alembic_db):
        """A 256-bit key cannot be meaningfully guessed, so there is no
        per-account lockout and therefore nothing durable to back it with."""
        command.upgrade(_alembic_config(), "head")
        assert "login_attempts" not in _table_names(alembic_db)

    def test_a_database_alembic_created_works_with_the_app(self, alembic_db):
        """The app's own startup hooks must run cleanly on a schema Alembic
        created first -- CREATE TABLE IF NOT EXISTS makes this a no-op, but
        that is exactly the assumption worth pinning down."""
        command.upgrade(_alembic_config(), "head")
        db.init_db()
        auth.init_auth_schema()
        user_id, key = auth.create_user("smoketest", "drafter")
        assert user_id is not None
        assert auth.authenticate_key(key)["username"] == "smoketest"


class TestOrderingIndependence:
    """The two ways a database comes into being must agree."""

    def test_app_init_after_alembic_upgrade_is_a_no_op(self, alembic_db):
        """Alembic first, then the app's own startup hooks on top."""
        command.upgrade(_alembic_config(), "head")

        db.init_db()
        auth.init_auth_schema()  # must not raise on an already-correct schema

        assert _table_names(alembic_db) == EXPECTED_TABLES
        assert auth.list_users() == []

    def test_alembic_stamp_after_app_init_marks_it_current(self, alembic_db):
        """The app creates its own schema first (the zero-config path); a
        later `alembic stamp head` should mark it current without re-running
        any SQL or touching the data already in it."""
        db.init_db()
        auth.init_auth_schema()
        user_id, key = auth.create_user("smoketest", "drafter")
        assert user_id is not None

        command.stamp(_alembic_config(), "head")

        conn = sqlite3.connect(alembic_db)
        try:
            version = conn.execute(
                "SELECT version_num FROM alembic_version"
            ).fetchone()
        finally:
            conn.close()
        assert version is not None

        # Data survived the stamp untouched.
        assert auth.authenticate_key(key)["username"] == "smoketest"
