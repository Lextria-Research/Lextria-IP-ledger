"""baseline: existing ledger and auth schema

This is a baseline, not a change: it recreates -- verbatim, via raw SQL --
the schema that backend/db.py:init_db() and backend/auth.py:init_auth_schema()
already build with CREATE TABLE IF NOT EXISTS on every app startup. It exists
so that from here on, any ACTUAL schema change (an ALTER TABLE, a new column)
has a migration chain to attach to, rather than being a second, undocumented
edit to those CREATE TABLE strings.

On a fresh database `alembic upgrade head` creates the schema outright (the
IF NOT EXISTS guards make that safe even if the app already created it first).
On an existing installation, running the app has already created every table
below, so this revision should instead be applied with `alembic stamp head`
-- marking it as already-satisfied without re-running its SQL. Either way,
the two CREATE TABLE call sites in backend/db.py and backend/auth.py are
still what actually runs at app startup; this migration does not replace or
disable them, it only gives future schema changes a place to live.

Revision ID: 5622988fbb5f
Revises:
Create Date: 2026-09-15 21:57:52.373786

"""
from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = '5622988fbb5f'
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Verbatim copy of backend/db.py:init_db()'s executescript body.
    op.execute("""
        CREATE TABLE IF NOT EXISTS ledger_state (
            id          INTEGER PRIMARY KEY CHECK (id = 1),
            document    TEXT    NOT NULL,
            revision    INTEGER NOT NULL DEFAULT 1,
            updated_at  TEXT    NOT NULL
        )
    """)
    op.execute("""
        CREATE TABLE IF NOT EXISTS ledger_history (
            revision    INTEGER PRIMARY KEY,
            document    TEXT    NOT NULL,
            saved_at    TEXT    NOT NULL
        )
    """)

    # Verbatim copy of backend/auth.py:init_auth_schema()'s executescript body.
    op.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            username      TEXT    NOT NULL UNIQUE COLLATE NOCASE,
            password_hash TEXT    NOT NULL,
            role          TEXT    NOT NULL,
            active        INTEGER NOT NULL DEFAULT 1,
            created_at    TEXT    NOT NULL
        )
    """)
    op.execute("""
        CREATE TABLE IF NOT EXISTS sessions (
            token      TEXT    PRIMARY KEY,
            user_id    INTEGER NOT NULL,
            created_at TEXT    NOT NULL,
            expires_at TEXT    NOT NULL,
            FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
        )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS idx_sessions_user ON sessions(user_id)")
    op.execute("""
        CREATE TABLE IF NOT EXISTS login_attempts (
            id       INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT NOT NULL,
            at       TEXT NOT NULL
        )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS idx_attempts ON login_attempts(username, at)")
    op.execute("""
        CREATE TABLE IF NOT EXISTS login_history (
            id       INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT    NOT NULL,
            success  INTEGER NOT NULL,
            ip       TEXT    NOT NULL,
            at       TEXT    NOT NULL
        )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS idx_history_at ON login_history(at)")


def downgrade() -> None:
    # Destructive by nature (this is the whole schema) -- present for
    # completeness, not for routine use on a database with real data in it.
    op.execute("DROP INDEX IF EXISTS idx_history_at")
    op.execute("DROP TABLE IF EXISTS login_history")
    op.execute("DROP INDEX IF EXISTS idx_attempts")
    op.execute("DROP TABLE IF EXISTS login_attempts")
    op.execute("DROP INDEX IF EXISTS idx_sessions_user")
    op.execute("DROP TABLE IF EXISTS sessions")
    op.execute("DROP TABLE IF EXISTS users")
    op.execute("DROP TABLE IF EXISTS ledger_history")
    op.execute("DROP TABLE IF EXISTS ledger_state")
