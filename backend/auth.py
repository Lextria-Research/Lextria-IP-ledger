"""Accounts, access keys and sessions.

Authentication is by access key only -- there are no passwords. Every account
has its own key, which is what lets the server know WHO is calling and apply
that account's role. (One shared key for the whole firm could not do that: the
server would have no way to tell a super admin from a trademark admin, so it
could not keep financial data from either.)

A key is 256 bits from `secrets`, shown exactly once when it is issued, and
stored only as a SHA-256 hash. Because the key itself is random and that long,
a fast hash is the right tool here: key-stretching (PBKDF2, bcrypt) exists to
protect guessable human passwords, and there is nothing guessable to protect.
It also lets a key be looked up directly by its hash, so no account name has
to accompany it.

A key can be used two ways:
  - the browser trades it once at POST /api/login for an HttpOnly session
    cookie, so the key never has to sit in page storage where an XSS could
    read it;
  - a script sends it on every request as `Authorization: Bearer <key>` or
    `X-Lextria-Key: <key>`.

No environment configuration and no third-party dependency: accounts live in the
same SQLite file as the ledger.
"""

import hashlib
import secrets
import sqlite3
import threading
import time
from datetime import datetime, timedelta, timezone

from . import db, roles

KEY_PREFIX = "lx_"
KEY_BYTES = 32            # 256 bits of entropy
KEY_HINT_CHARS = 6        # how much of a key is kept in clear, to tell keys apart

SESSION_COOKIE = "lextria_session"
SESSION_HOURS = 12


def _now():
    return datetime.now(timezone.utc)


def _iso(dt):
    return dt.isoformat(timespec="seconds")


# --- Keys -------------------------------------------------------------------

def generate_key():
    return KEY_PREFIX + secrets.token_urlsafe(KEY_BYTES)


def hash_key(key):
    return hashlib.sha256((key or "").encode("utf-8")).hexdigest()


def key_hint(key):
    """A short, non-secret fragment ("lx_Ab3dE9…") that lets a super admin tell
    which key an account currently has without the key being recoverable."""
    return key[:len(KEY_PREFIX) + KEY_HINT_CHARS] + "…"


def looks_like_key(value):
    return isinstance(value, str) and value.startswith(KEY_PREFIX) and len(value) > 20


# --- Schema -----------------------------------------------------------------

def init_auth_schema():
    """Create the auth tables. Safe to call on every startup."""
    with db._write_lock, db._connect() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS users (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                username    TEXT    NOT NULL UNIQUE COLLATE NOCASE,
                key_hash    TEXT    NOT NULL UNIQUE,
                key_hint    TEXT    NOT NULL,
                role        TEXT    NOT NULL,
                active      INTEGER NOT NULL DEFAULT 1,
                created_at  TEXT    NOT NULL,
                key_issued_at TEXT  NOT NULL
            );

            CREATE TABLE IF NOT EXISTS sessions (
                token      TEXT    PRIMARY KEY,
                user_id    INTEGER NOT NULL,
                created_at TEXT    NOT NULL,
                expires_at TEXT    NOT NULL,
                FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
            );

            CREATE INDEX IF NOT EXISTS idx_sessions_user ON sessions(user_id);

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
        columns = {r["name"] for r in conn.execute("PRAGMA table_info(users)")}
        if "key_hash" not in columns:
            # A database from the password-based version. Its accounts have no
            # key and cannot be given one without someone being told it, so
            # starting them over is the only honest option -- refuse loudly
            # rather than run with accounts nobody can sign in to.
            raise RuntimeError(
                "backend/lextria.db was created by the password-based version and "
                "has no access keys. Move it aside (the ledger is in its "
                "ledger_state table) and restart to create fresh accounts.")


# --- Accounts ---------------------------------------------------------------

def create_user(username, role):
    """Create an account. Returns (id, key), or (None, None) if the name is taken.

    The key is returned here and nowhere else, ever: only its hash is stored.
    """
    if role not in roles.ALL_ROLES:
        raise ValueError("unknown role: %s" % role)
    username = (username or "").strip()
    if not username:
        raise ValueError("username required")

    key = generate_key()
    stamp = _iso(_now())
    with db._write_lock, db._connect() as conn:
        try:
            cur = conn.execute(
                "INSERT INTO users (username, key_hash, key_hint, role, active,"
                " created_at, key_issued_at) VALUES (?, ?, ?, ?, 1, ?, ?)",
                (username, hash_key(key), key_hint(key), role, stamp, stamp),
            )
        except sqlite3.IntegrityError:
            return None, None
        return cur.lastrowid, key


def rotate_key(user_id):
    """Issue a new key for an account and sign it out everywhere.

    Returns the new key, or None if there is no such account. The old key stops
    working immediately, and so does every session that was opened with it --
    the usual reason to replace a key is that it may be known to someone else.
    """
    key = generate_key()
    with db._write_lock, db._connect() as conn:
        cur = conn.execute(
            "UPDATE users SET key_hash = ?, key_hint = ?, key_issued_at = ? WHERE id = ?",
            (hash_key(key), key_hint(key), _iso(_now()), user_id),
        )
        if not cur.rowcount:
            return None
        conn.execute("DELETE FROM sessions WHERE user_id = ?", (user_id,))
    return key


def set_active(user_id, active):
    """Suspend or restore an account. Suspending also ends its live sessions --
    otherwise it keeps working until its cookie expires, which is not what
    "suspend" means."""
    with db._write_lock, db._connect() as conn:
        cur = conn.execute("UPDATE users SET active = ? WHERE id = ?",
                           (1 if active else 0, user_id))
        if cur.rowcount and not active:
            conn.execute("DELETE FROM sessions WHERE user_id = ?", (user_id,))
        return cur.rowcount > 0


def set_role(user_id, role):
    """Change an account's role, ending its sessions so the change takes effect
    on the next request rather than whenever the cookie happens to expire."""
    if role not in roles.ALL_ROLES:
        raise ValueError("unknown role: %s" % role)
    with db._write_lock, db._connect() as conn:
        cur = conn.execute("UPDATE users SET role = ? WHERE id = ?", (role, user_id))
        if cur.rowcount:
            conn.execute("DELETE FROM sessions WHERE user_id = ?", (user_id,))
        return cur.rowcount > 0


def list_users():
    """Every account, without its key hash."""
    with db._connect() as conn:
        rows = conn.execute(
            "SELECT id, username, role, active, created_at, key_hint, key_issued_at"
            " FROM users ORDER BY id"
        ).fetchall()
    return [dict(r) for r in rows]


def active_usernames():
    return [u["username"] for u in list_users() if u["active"]]


def get_user_by_name(username):
    with db._connect() as conn:
        row = conn.execute(
            "SELECT id, username, role, active FROM users WHERE username = ?",
            (username,),
        ).fetchone()
    return dict(row) if row else None


def delete_user(user_id):
    with db._write_lock, db._connect() as conn:
        conn.execute("DELETE FROM sessions WHERE user_id = ?", (user_id,))
        cur = conn.execute("DELETE FROM users WHERE id = ?", (user_id,))
        return cur.rowcount > 0


def count_active_superadmins(excluding_id=None):
    """Active superadmins, optionally ignoring one account -- the guard behind
    "you cannot remove the last super admin"."""
    sql = "SELECT COUNT(*) AS n FROM users WHERE role = ? AND active = 1"
    params = [roles.SUPERADMIN]
    if excluding_id is not None:
        sql += " AND id != ?"
        params.append(excluding_id)
    with db._connect() as conn:
        return conn.execute(sql, params).fetchone()["n"]


def authenticate_key(key):
    """The active account a key belongs to, or None."""
    if not looks_like_key(key):
        return None
    with db._connect() as conn:
        row = conn.execute(
            "SELECT id, username, role, active FROM users WHERE key_hash = ?",
            (hash_key(key),),
        ).fetchone()
    if row is None or not row["active"]:
        return None
    return {"id": row["id"], "username": row["username"], "role": row["role"]}


# --- Rate limiting (per source address, in memory) -------------------------
#
# A 256-bit key cannot be guessed, so there is no per-account lockout: a caller
# offering a wrong key names no account to lock. What is still worth capping is
# how hard one address can hammer the key check -- sign-in attempts, and failed
# keys sent on API requests -- which keeps logs, CPU and the login history from
# being flooded.
#
# Kept in an in-process dict rather than SQLite on purpose: nothing here is
# worth surviving a restart, and it avoids a disk write per request.

IP_MAX_ATTEMPTS = 20
IP_WINDOW_SECONDS = 300

_ip_attempts = {}
_ip_lock = threading.Lock()


def reset_ip_limiter():
    """Clear the in-memory counters. Only meaningful for tests, which all share
    one process and one fake client address."""
    with _ip_lock:
        _ip_attempts.clear()


def _prune(times, cutoff):
    while times and times[0] < cutoff:
        times.pop(0)


def ip_wait_seconds(ip):
    """Seconds this address must wait before its key may be checked again, or 0."""
    if not ip:
        return 0
    now = time.monotonic()
    with _ip_lock:
        times = _ip_attempts.get(ip)
        if not times:
            return 0
        _prune(times, now - IP_WINDOW_SECONDS)
        if len(times) >= IP_MAX_ATTEMPTS:
            return max(1, int(IP_WINDOW_SECONDS - (now - times[0])))
        return 0


def record_ip_attempt(ip):
    """Count one attempt against this address."""
    if not ip:
        return
    now = time.monotonic()
    cutoff = now - IP_WINDOW_SECONDS
    with _ip_lock:
        times = _ip_attempts.setdefault(ip, [])
        _prune(times, cutoff)
        times.append(now)
        # Bound memory across the life of the process.
        if len(_ip_attempts) > 10000:
            for k in [k for k, v in _ip_attempts.items() if not v or v[-1] < cutoff]:
                _ip_attempts.pop(k, None)


# --- Sessions ---------------------------------------------------------------

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
    """The user for a session token, or None if unknown/expired/suspended."""
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
    """Sign this account out everywhere except the session making the request --
    for "I left myself signed in somewhere", without replacing the key."""
    with db._write_lock, db._connect() as conn:
        conn.execute(
            "DELETE FROM sessions WHERE user_id = ? AND token != ?",
            (user_id, keep_token or ""),
        )


def purge_expired_sessions():
    with db._write_lock, db._connect() as conn:
        conn.execute("DELETE FROM sessions WHERE expires_at < ?", (_iso(_now()),))


# --- Login history ----------------------------------------------------------
#
# A durable record of sign-in attempts, so a super admin can see whether someone
# is trying keys against the server. A failed attempt names no account (a wrong
# key belongs to nobody), and the key itself is never written down.

LOGIN_HISTORY_LIMIT = 500
UNKNOWN_KEY = "(unrecognised key)"


def record_login_event(username, success, ip):
    with db._write_lock, db._connect() as conn:
        conn.execute(
            "INSERT INTO login_history (username, success, ip, at) VALUES (?, ?, ?, ?)",
            ((username or UNKNOWN_KEY).strip(), 1 if success else 0,
             ip or "unknown", _iso(_now())),
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


# --- First run --------------------------------------------------------------

def ensure_superadmin():
    """Create the superadmin on first run.

    Returns its key the one time it creates the account, and None on every later
    start. Only the hash is stored, so a lost key is replaced with
    `py -m backend.manage rotate superadmin`, not recovered.
    """
    with db._connect() as conn:
        existing = conn.execute(
            "SELECT COUNT(*) AS n FROM users WHERE role = ?", (roles.SUPERADMIN,)
        ).fetchone()
    if existing["n"] > 0:
        return None
    _user_id, key = create_user("superadmin", roles.SUPERADMIN)
    return key
