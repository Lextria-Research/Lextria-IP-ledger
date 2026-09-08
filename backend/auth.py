"""User accounts, password hashing and sessions.

No environment configuration and no third-party dependency: accounts live in
the same SQLite file as the ledger, and hashing uses PBKDF2-HMAC-SHA256 from
the standard library.

On first run, a `superadmin` account is created with a random password that is
printed to the console exactly once -- there is nowhere else to read it from,
because only its hash is stored.
"""

import hashlib
import hmac
import secrets
import sqlite3
from datetime import datetime, timedelta, timezone

from . import db, roles

# PBKDF2 cost. 600k matches OWASP's 2023 guidance for SHA-256 and keeps a login
# around a tenth of a second, which is unnoticeable to a person and expensive
# in bulk to anyone working through a stolen database.
PBKDF2_ITERATIONS = 600_000

SESSION_COOKIE = "lextria_session"
SESSION_HOURS = 12

# Password length for the auto-generated superadmin. token_urlsafe(12) is ~96
# bits of entropy -- long enough that the account is not worth guessing, short
# enough to retype from a terminal.
GENERATED_PASSWORD_BYTES = 12


def _now():
    return datetime.now(timezone.utc)


def _iso(dt):
    return dt.isoformat(timespec="seconds")


def hash_password(password, salt=None):
    """Return a self-describing 'pbkdf2_sha256$iterations$salt$hash' string."""
    if salt is None:
        salt = secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac(
        "sha256", password.encode("utf-8"), salt.encode("utf-8"), PBKDF2_ITERATIONS
    )
    return "pbkdf2_sha256$%d$%s$%s" % (PBKDF2_ITERATIONS, salt, digest.hex())


def verify_password(password, stored):
    """Constant-time check of a password against a stored hash string."""
    try:
        algorithm, iterations, salt, expected = stored.split("$", 3)
    except (ValueError, AttributeError):
        return False
    if algorithm != "pbkdf2_sha256":
        return False
    try:
        iterations = int(iterations)
    except ValueError:
        return False
    digest = hashlib.pbkdf2_hmac(
        "sha256", password.encode("utf-8"), salt.encode("utf-8"), iterations
    )
    # compare_digest, not ==, so a wrong password cannot be narrowed down by
    # timing how long the comparison took.
    return hmac.compare_digest(digest.hex(), expected)


def init_auth_schema():
    """Create the auth tables. Safe to call on every startup."""
    with db._write_lock, db._connect() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS users (
                id            INTEGER PRIMARY KEY AUTOINCREMENT,
                username      TEXT    NOT NULL UNIQUE COLLATE NOCASE,
                password_hash TEXT    NOT NULL,
                role          TEXT    NOT NULL,
                active        INTEGER NOT NULL DEFAULT 1,
                created_at    TEXT    NOT NULL
            );

            CREATE TABLE IF NOT EXISTS sessions (
                token      TEXT    PRIMARY KEY,
                user_id    INTEGER NOT NULL,
                created_at TEXT    NOT NULL,
                expires_at TEXT    NOT NULL,
                FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
            );

            CREATE INDEX IF NOT EXISTS idx_sessions_user ON sessions(user_id);

            CREATE TABLE IF NOT EXISTS login_attempts (
                id       INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT NOT NULL,
                at       TEXT NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_attempts ON login_attempts(username, at);
            """
        )


def create_user(username, password, role):
    """Create an account. Returns its id, or None if the name is taken."""
    if role not in roles.ALL_ROLES:
        raise ValueError("unknown role: %s" % role)
    username = (username or "").strip()
    if not username:
        raise ValueError("username required")
    if not password:
        raise ValueError("password required")

    with db._write_lock, db._connect() as conn:
        try:
            cur = conn.execute(
                "INSERT INTO users (username, password_hash, role, active, created_at)"
                " VALUES (?, ?, ?, 1, ?)",
                (username, hash_password(password), role, _iso(_now())),
            )
        except sqlite3.IntegrityError:
            return None
        return cur.lastrowid


def set_password(username, password):
    """Change a password and sign that account out everywhere.

    Ending the sessions is the point of the reset: the usual reason to change a
    password is that it may be known to someone else, and leaving their live
    session working for another 12 hours defeats the exercise.
    """
    with db._write_lock, db._connect() as conn:
        cur = conn.execute(
            "UPDATE users SET password_hash = ? WHERE username = ?",
            (hash_password(password), username),
        )
        if cur.rowcount:
            conn.execute(
                "DELETE FROM sessions WHERE user_id IN"
                " (SELECT id FROM users WHERE username = ?)",
                (username,),
            )
        return cur.rowcount > 0


def set_active(user_id, active):
    """Suspend or restore an account.

    Suspending also ends its live sessions -- otherwise the account keeps
    working until its cookie expires, which is not what "suspend" means.
    """
    with db._write_lock, db._connect() as conn:
        cur = conn.execute("UPDATE users SET active = ? WHERE id = ?",
                           (1 if active else 0, user_id))
        if cur.rowcount and not active:
            conn.execute("DELETE FROM sessions WHERE user_id = ?", (user_id,))
        return cur.rowcount > 0


def set_role(user_id, role):
    """Change an account's role, ending its sessions.

    The role is baked into the session's view of the ledger, so an open session
    would keep the old permissions until it expired.
    """
    if role not in roles.ALL_ROLES:
        raise ValueError("unknown role: %s" % role)
    with db._write_lock, db._connect() as conn:
        cur = conn.execute("UPDATE users SET role = ? WHERE id = ?", (role, user_id))
        if cur.rowcount:
            conn.execute("DELETE FROM sessions WHERE user_id = ?", (user_id,))
        return cur.rowcount > 0


def list_users():
    with db._connect() as conn:
        rows = conn.execute(
            "SELECT id, username, role, active, created_at FROM users ORDER BY id"
        ).fetchall()
    return [dict(r) for r in rows]


def get_user_by_name(username):
    with db._connect() as conn:
        row = conn.execute(
            "SELECT * FROM users WHERE username = ?", (username,)
        ).fetchone()
    return dict(row) if row else None


def delete_user(user_id):
    with db._write_lock, db._connect() as conn:
        conn.execute("DELETE FROM sessions WHERE user_id = ?", (user_id,))
        cur = conn.execute("DELETE FROM users WHERE id = ?", (user_id,))
        return cur.rowcount > 0


def authenticate(username, password):
    """Return the user dict on success, else None."""
    user = get_user_by_name((username or "").strip())
    if user is None:
        # Hash anyway, so that a missing username and a wrong password take the
        # same time and cannot be told apart by an attacker enumerating names.
        hash_password(password or "")
        return None
    if not user["active"]:
        return None
    if not verify_password(password or "", user["password_hash"]):
        return None
    return user


def authenticate_throttled(username, password):
    """authenticate(), with lockout. Returns (user, seconds_locked_out)."""
    username = (username or "").strip()
    wait = lockout_seconds_remaining(username)
    if wait:
        return None, wait
    user = authenticate(username, password)
    if user is None:
        _record_failure(username)
        return None, lockout_seconds_remaining(username)
    _clear_failures(username)
    return user, 0


# --- Login throttling -------------------------------------------------------
#
# A 600k-iteration hash makes an OFFLINE attack on a stolen database expensive.
# It does nothing about someone simply POSTing guesses at /api/login, which is
# the cheaper attack when the server is reachable. These limits make an online
# guessing run impractical without locking a real user out for long.

MAX_FAILURES = 5          # consecutive failures before a lockout
LOCKOUT_SECONDS = 300     # how long the lockout lasts
FAILURE_WINDOW_SECONDS = 900   # failures older than this stop counting


def _record_failure(username):
    with db._write_lock, db._connect() as conn:
        conn.execute("INSERT INTO login_attempts (username, at) VALUES (?, ?)",
                     (username.lower(), _iso(_now())))
        # Keep the table from growing without bound.
        cutoff = _iso(_now() - timedelta(seconds=FAILURE_WINDOW_SECONDS * 4))
        conn.execute("DELETE FROM login_attempts WHERE at < ?", (cutoff,))


def _clear_failures(username):
    with db._write_lock, db._connect() as conn:
        conn.execute("DELETE FROM login_attempts WHERE username = ?", (username.lower(),))


def lockout_seconds_remaining(username):
    """Seconds this account must wait, or 0 if it may attempt a sign-in."""
    if not username:
        return 0
    since = _iso(_now() - timedelta(seconds=FAILURE_WINDOW_SECONDS))
    with db._connect() as conn:
        rows = conn.execute(
            "SELECT at FROM login_attempts WHERE username = ? AND at >= ?"
            " ORDER BY at DESC LIMIT ?",
            (username.lower(), since, MAX_FAILURES),
        ).fetchall()
    if len(rows) < MAX_FAILURES:
        return 0
    newest = datetime.fromisoformat(rows[0]["at"])
    elapsed = (_now() - newest).total_seconds()
    remaining = LOCKOUT_SECONDS - elapsed
    return int(remaining) if remaining > 0 else 0


def start_session(user_id):
    token = secrets.token_urlsafe(32)
    now = _now()
    with db._write_lock, db._connect() as conn:
        conn.execute(
            "INSERT INTO sessions (token, user_id, created_at, expires_at)"
            " VALUES (?, ?, ?, ?)",
            (token, user_id, _iso(now), _iso(now + timedelta(hours=SESSION_HOURS))),
        )
    return token


def session_user(token):
    """The user for a session token, or None if unknown/expired."""
    if not token:
        return None
    with db._connect() as conn:
        row = conn.execute(
            "SELECT u.id, u.username, u.role, u.active, s.expires_at"
            " FROM sessions s JOIN users u ON u.id = s.user_id"
            " WHERE s.token = ?",
            (token,),
        ).fetchone()
    if row is None:
        return None
    if datetime.fromisoformat(row["expires_at"]) < _now():
        end_session(token)
        return None
    if not row["active"]:
        return None
    return {"id": row["id"], "username": row["username"], "role": row["role"]}


def end_session(token):
    if not token:
        return
    with db._write_lock, db._connect() as conn:
        conn.execute("DELETE FROM sessions WHERE token = ?", (token,))


def purge_expired_sessions():
    with db._write_lock, db._connect() as conn:
        conn.execute("DELETE FROM sessions WHERE expires_at < ?", (_iso(_now()),))


def ensure_superadmin():
    """Create the superadmin on first run.

    Returns the generated password the one time it creates the account, and
    None on every later start. Only the hash is stored, so a lost password is
    reset with `py -m backend.manage passwd superadmin`, not recovered.
    """
    with db._connect() as conn:
        existing = conn.execute(
            "SELECT COUNT(*) AS n FROM users WHERE role = ?", (roles.SUPERADMIN,)
        ).fetchone()
    if existing["n"] > 0:
        return None

    password = secrets.token_urlsafe(GENERATED_PASSWORD_BYTES)
    create_user("superadmin", password, roles.SUPERADMIN)
    return password
