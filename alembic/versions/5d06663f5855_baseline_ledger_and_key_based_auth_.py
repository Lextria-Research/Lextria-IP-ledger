"""baseline: ledger and key-based auth schema

This is a baseline, not a change: it recreates -- verbatim, via raw SQL -- the
schema that backend/db.py:init_db() and backend/auth.py:init_auth_schema()
already build with CREATE TABLE IF NOT EXISTS on every app startup. It exists
so that from here on, any ACTUAL schema change (an ALTER TABLE, a new column)
has a migration chain to attach to, rather than being a second, undocumented
edit to those CREATE TABLE strings.

On a fresh database `alembic upgrade head` creates the schema outright (the
IF NOT EXISTS guards make that safe even if the app already created it first
by running once without Alembic). On an existing installation whose database
predates this file, running the app has already created every table below --
apply this revision there with `alembic stamp head` instead, which marks it
satisfied without re-running its SQL.

Either way, the two CREATE TABLE call sites in backend/db.py and
backend/auth.py are still what actually runs at app startup; this migration
does not replace or disable them, it only gives future schema changes a place
to live. See README.md's "Database migrations" section.

Authentication here is by access key, not password: `users.key_hash` /
`key_hint` / `key_issued_at`, not a `password_hash` column, and there is no
`login_attempts` table -- a 256-bit key cannot be meaningfully guessed, so
there is no per-account lockout to back with durable state (the per-address
rate limit in backend/auth.py is deliberately in-memory only; see its module
docstring).

Revision ID: 5d06663f5855
Revises:
Create Date: 2026-09-17 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = '5d06663f5855'
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
            key_hash      TEXT    NOT NULL UNIQUE,
            key_hint      TEXT    NOT NULL,
            role          TEXT    NOT NULL,
            active        INTEGER NOT NULL DEFAULT 1,
            created_at    TEXT    NOT NULL,
            key_issued_at TEXT    NOT NULL
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
    # Deliberately a no-op rather than DROP TABLE. This is the FIRST revision;
    # "downgrading" it means deleting the entire ledger and every account, which
    # is not a schema rollback, it is data loss, and Alembic is not the tool
    # for that decision. Restore from a backup of backend/lextria.db instead --
    # see README.md's "Storage" section.
    pass
