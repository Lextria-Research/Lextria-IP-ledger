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
import threading
import time
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

            CREATE TABLE IF NOT EXISTS login_history (
                id       INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT    NOT NULL,
                success  INTEGER NOT NULL,
                ip       TEXT    NOT NULL,
                at       TEXT    NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_history_at ON login_history(at);
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


# --- Login throttling (per account, durable) --------------------------------
#
# A 600k-iteration hash makes an OFFLINE attack on a stolen database expensive.
# It does nothing about someone simply POSTing guesses at /api/login, which is
# the cheaper attack when the server is reachable. This limit makes an online
# guessing run against ONE account impractical without locking it out for long.
# Persisted in SQLite, so it survives a server restart.

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


# --- Login rate limiting (per source address, in memory) --------------------
#
# Separate from the per-account lockout above, and deliberately NOT persisted:
# this caps how many /api/login REQUESTS one address may make at all, success
# or failure, regardless of which username(s) it tries -- the gap the
# per-account limit alone leaves open, since spraying one guess across many
# different usernames never makes any single account reach MAX_FAILURES.
#
# Kept in an in-process dict rather than SQLite on purpose: there is nothing
# here worth surviving a restart, a plain dict needs no schema (so there is
# nothing to migrate as this limit's shape changes), and it avoids a disk
# write on every single login request. It resets to empty whenever the server
# restarts, which simply means the count starts over -- an acceptable trade
# for a lightweight abuse guard rather than a durable record (that durable
# record is login_history, below).
IP_LOGIN_MAX_REQUESTS = 20
IP_LOGIN_WINDOW_SECONDS = 300

_ip_login_times = {}
_ip_login_lock = threading.Lock()


def reset_ip_login_limiter():
    """Clear the in-memory per-address counters.

    Only meaningful for tests: every test in a pytest run shares this one
    process (and every request through Starlette's TestClient reports the
    same fake source address), so without resetting this between tests, an
    early test's login attempts would count against a later, unrelated one.
    A real deployment never needs to call this -- restarting the process does
    the same thing, which is exactly what "not persisted" already means.
    """
    with _ip_login_lock:
        _ip_login_times.clear()


def ip_login_wait_seconds(ip):
    """Seconds this address must wait before its next /api/login request may
    proceed, or 0 if it may go ahead right now -- which this also records as
    one of its uses within the window, so this must be called at most once per
    actual request."""
    if not ip:
        return 0
    now = time.monotonic()
    cutoff = now - IP_LOGIN_WINDOW_SECONDS
    with _ip_login_lock:
        times = _ip_login_times.setdefault(ip, [])
        while times and times[0] < cutoff:
            times.pop(0)
        if len(times) >= IP_LOGIN_MAX_REQUESTS:
            return max(1, int(IP_LOGIN_WINDOW_SECONDS - (now - times[0])))
        times.append(now)
        # Bound memory: an address that has never been seen recently is
        # dropped, so this cannot grow forever across the life of the process.
        if len(_ip_login_times) > 10000:
            stale = [k for k, v in _ip_login_times.items() if not v or v[-1] < cutoff]
            for k in stale:
                _ip_login_times.pop(k, None)
        return 0


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


def end_other_sessions(user_id, keep_token):
    """Sign this account out everywhere except the session making the request.

    A password change already ends every session (the right default when the
    password itself may be compromised); this is the lighter-weight action for
    "I think I left myself logged in on a shared computer" -- no credential
    needs to change, just every OTHER session.
    """
    with db._write_lock, db._connect() as conn:
        conn.execute(
            "DELETE FROM sessions WHERE user_id = ? AND token != ?",
            (user_id, keep_token or ""),
        )


def active_session_count(user_id):
    with db._connect() as conn:
        row = conn.execute(
            "SELECT COUNT(*) AS n FROM sessions WHERE user_id = ? AND expires_at >= ?",
            (user_id, _iso(_now())),
        ).fetchone()
    return row["n"]


def purge_expired_sessions():
    with db._write_lock, db._connect() as conn:
        conn.execute("DELETE FROM sessions WHERE expires_at < ?", (_iso(_now()),))


# --- Login history ------------------------------------------------------
#
# Separate from login_attempts (a short-lived throttling cache that is pruned
# aggressively): this is a durable record of who tried to sign in, from where,
# and whether it worked, so a super admin can actually see whether an account
# is under attack rather than just feeling the lockout happen.

LOGIN_HISTORY_LIMIT = 500


def record_login_event(username, success, ip):
    with db._write_lock, db._connect() as conn:
        conn.execute(
            "INSERT INTO login_history (username, success, ip, at) VALUES (?, ?, ?, ?)",
            ((username or "").strip(), 1 if success else 0, ip or "unknown", _iso(_now())),
        )
        conn.execute(
            "DELETE FROM login_history WHERE id NOT IN"
            " (SELECT id FROM login_history ORDER BY id DESC LIMIT ?)",
            (LOGIN_HISTORY_LIMIT,),
        )


def recent_login_events(limit=100):
    limit = max(1, min(limit, LOGIN_HISTORY_LIMIT))
    with db._connect() as conn:
        rows = conn.execute(
            "SELECT username, success, ip, at FROM login_history"
            " ORDER BY id DESC LIMIT ?",
            (limit,),
        ).fetchall()
    return [dict(r) for r in rows]


# --- Password strength --------------------------------------------------
#
# The 8-character minimum (enforced by callers) stops a one-character
# password; it does nothing about "password1" or a password that is just the
# account's own username. This blocklist catches the handful of choices that
# are guessed in the first few seconds of any real attack, without pretending
# to be a full password-strength meter.

_WEAK_PASSWORDS = frozenset([
    "password", "password1", "password123", "12345678", "123456789",
    "1234567890", "qwertyui", "qwerty123", "letmein11", "welcome11",
    "admin1234", "changeme1", "abc123456", "iloveyou1", "superadmin",
    "trademark", "drafter123", "lextria123",
])


def is_weak_password(password, username=None):
    """A short, human-readable reason the password is too weak, or None."""
    pw = password or ""
    if pw.lower() in _WEAK_PASSWORDS:
        return "That password is far too common — choose something less guessable."
    if username and pw.lower() == username.strip().lower():
        return "The password cannot be the same as the username."
    if len(set(pw)) == 1:
        return "That password is a single character repeated — choose something with more variety."
    return None


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
