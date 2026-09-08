"""SQLite persistence for the Lextria IP Ledger.

The browser app treats its ledger as one JSON document and exchanges it whole
(GET /api/state -> the document, PUT /api/state -> replace the document), so
that is what this module stores: a single current document, plus a bounded
revision history.

The history is not exposed through the API — it exists so that a bad import or
an accidental "clear all" is recoverable by hand (`sqlite3 lextria.db`), which
matters more for a legal matter ledger than for most CRUD apps.
"""

import json
import sqlite3
import threading
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

# Where the database file lives. Kept next to the backend package so that
# running uvicorn from any working directory finds the same database.
DB_PATH = Path(__file__).resolve().parent / "lextria.db"

# How many superseded revisions to keep before the oldest are pruned.
HISTORY_LIMIT = 50

# The ledger shape index.html expects when nothing has been saved yet. Mirrors
# the seed in the page's <script id="app-state"> block.
EMPTY_STATE = {
    "clients": [],
    "records": [],
    "nextClientSeq": 1,
    "nextRecordSeq": 1,
    "log": [],
}

# sqlite3 connections are not safe to share across threads without care, and
# FastAPI serves requests from a threadpool, so every write is serialised.
_write_lock = threading.Lock()


@contextmanager
def _connect():
    """A connection that is committed on success, rolled back on error, and
    ALWAYS closed.

    sqlite3's own `with sqlite3.connect(...) as conn:` is a transaction context
    manager, not a closing one -- it commits, then leaves the connection open.
    Relying on refcounting to close it is not deterministic, and under WAL each
    lingering connection holds file handles and blocks -wal/-shm cleanup. This
    wrapper is the reason every caller can safely say `with _connect() as conn`.
    """
    conn = sqlite3.connect(DB_PATH, timeout=10)
    try:
        conn.row_factory = sqlite3.Row
        # WAL lets reads proceed while a write is in flight; without it a slow
        # save blocks every dashboard refresh.
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db() -> None:
    """Create the schema. Safe to call on every startup."""
    with _write_lock, _connect() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS ledger_state (
                id          INTEGER PRIMARY KEY CHECK (id = 1),
                document    TEXT    NOT NULL,
                revision    INTEGER NOT NULL DEFAULT 1,
                updated_at  TEXT    NOT NULL
            );

            CREATE TABLE IF NOT EXISTS ledger_history (
                revision    INTEGER PRIMARY KEY,
                document    TEXT    NOT NULL,
                saved_at    TEXT    NOT NULL
            );
            """
        )


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def load_state():
    """Return the saved ledger document, or None if nothing has been saved.

    None (rather than an empty ledger) is deliberate: index.html falls back to
    the seed embedded in the page when the backend reports no state, and that
    distinction is what makes a first run show the seed instead of a blank slate.
    """
    with _connect() as conn:
        row = conn.execute(
            "SELECT document FROM ledger_state WHERE id = 1"
        ).fetchone()
    if row is None:
        return None
    try:
        return json.loads(row["document"])
    except json.JSONDecodeError:
        # A corrupt row should not take the whole app down; the client will
        # fall back to its embedded seed and the bad row stays for inspection.
        return None


def save_state(document: dict) -> int:
    """Replace the stored ledger. Returns the new revision number."""
    payload = json.dumps(document, ensure_ascii=False, separators=(",", ":"))
    stamp = _now()

    with _write_lock, _connect() as conn:
        row = conn.execute(
            "SELECT document, revision FROM ledger_state WHERE id = 1"
        ).fetchone()

        if row is None:
            revision = 1
        else:
            revision = row["revision"] + 1
            # Archive the version being replaced, not the one arriving.
            conn.execute(
                "INSERT OR REPLACE INTO ledger_history (revision, document, saved_at)"
                " VALUES (?, ?, ?)",
                (row["revision"], row["document"], stamp),
            )
            conn.execute(
                "DELETE FROM ledger_history WHERE revision <= ?",
                (revision - HISTORY_LIMIT,),
            )

        conn.execute(
            "INSERT INTO ledger_state (id, document, revision, updated_at)"
            " VALUES (1, ?, ?, ?)"
            " ON CONFLICT(id) DO UPDATE SET"
            "   document = excluded.document,"
            "   revision = excluded.revision,"
            "   updated_at = excluded.updated_at",
            (payload, revision, stamp),
        )

    return revision
