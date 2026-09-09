"""Tests for the additional security features layered on afterward:

- an in-memory per-address login rate limit (not per-account, not persisted)
- a durable login history / audit trail
- "sign out other devices" without a password change
- a weak-password blocklist
- the extra response headers

Per-account login throttling itself (backend/auth.py's MAX_FAILURES, backed by
SQLite) is covered in test_hardening.py.
"""

import pathlib
import sys

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from backend import auth, db, roles, security  # noqa: E402


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "secfeat.db")
    from backend.main import app
    with TestClient(app, base_url="http://localhost") as c:
        auth.create_user("boss", "bosspassword", roles.SUPERADMIN)
        auth.create_user("tma", "tmapassword", roles.TRADEMARK_ADMIN)
        auth.create_user("dee", "deepassword", roles.DRAFTER)
        yield c


def login(c, u, p, **kw):
    return c.post("/api/login", json={"username": u, "password": p}, **kw)


def fresh():
    from backend.main import app
    return TestClient(app, base_url="http://localhost")


# --- In-memory per-address login rate limit ---------------------------------
#
# Deliberately not persisted -- see auth.ip_login_wait_seconds. The autouse
# fixture in conftest.py resets this counter before and after every test, since
# it is a module-level store shared by the whole pytest process and every
# TestClient request reports the same fake source address.

def test_many_usernames_from_one_address_eventually_rate_limits_it(env):
    """The gap per-account throttling alone leaves open: spray one guess across
    many different accounts, and no single account ever reaches MAX_FAILURES."""
    for i in range(auth.IP_LOGIN_MAX_REQUESTS + 2):
        r = login(env, "user-that-does-not-exist-%d" % i, "wrongpassword")
    assert r.status_code == 429


def test_rate_limit_blocks_a_brand_new_username_too(env):
    for i in range(auth.IP_LOGIN_MAX_REQUESTS):
        login(env, "nobody-%d" % i, "wrong")
    # Even a username that has never been tried before is blocked, because the
    # limit is on the SOURCE making the requests, not on any one account.
    r = login(env, "yet-another-new-name", "wrong")
    assert r.status_code == 429


def test_rate_limit_counts_successful_attempts_too(env):
    """This is a REQUEST cap, not a failure cap -- correct logins count too,
    since the point is bounding volume from one source, not guessing quality."""
    for _ in range(auth.IP_LOGIN_MAX_REQUESTS):
        login(env, "boss", "bosspassword")  # every one of these succeeds
    r = login(env, "boss", "bosspassword")
    assert r.status_code == 429


def test_rate_limit_resets_after_the_window(env, monkeypatch):
    for i in range(auth.IP_LOGIN_MAX_REQUESTS):
        login(env, "nobody-%d" % i, "wrong")
    assert login(env, "boss", "bosspassword").status_code == 429

    # Simulate the window having elapsed, rather than actually sleeping 5
    # minutes: age every recorded timestamp out of the window.
    import time as _time
    with auth._ip_login_lock:
        for addr in auth._ip_login_times:
            auth._ip_login_times[addr] = [
                t - auth.IP_LOGIN_WINDOW_SECONDS - 1 for t in auth._ip_login_times[addr]
            ]
    assert login(env, "boss", "bosspassword").status_code == 200


def test_account_lockout_still_works_independently_of_the_rate_limit(env):
    """Well under the 20-request address limit, the per-account lockout (5
    failures, backend/auth.py's separate, SQLite-backed MAX_FAILURES) must
    still fire on its own."""
    for _ in range(auth.MAX_FAILURES):
        login(env, "boss", "wrong")
    r = login(env, "boss", "bosspassword")
    assert r.status_code == 429


def test_rate_limiter_state_is_in_memory_only(tmp_path, monkeypatch):
    """No table, no column, nothing on disk for this limit -- restarting the
    process (a fresh login_attempts table with nothing unexpected in it) is
    the whole story, unlike the durable per-account lockout above."""
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "ram_only.db")
    db.init_db()
    auth.init_auth_schema()
    auth.ip_login_wait_seconds("203.0.113.9")  # exercise the limiter
    with db._connect() as conn:
        cols = {r["name"] for r in conn.execute(
            "PRAGMA table_info(login_attempts)").fetchall()}
    assert cols == {"id", "username", "at"}  # untouched by the address limiter


# --- Login history / audit trail --------------------------------------------

def test_login_history_records_success_and_failure(env):
    login(env, "boss", "wrong")
    login(env, "boss", "bosspassword")
    login(env, "boss", "bosspassword")

    events = auth.recent_login_events()
    boss_events = [e for e in events if e["username"] == "boss"]
    assert len(boss_events) >= 3
    assert [e["success"] for e in boss_events[:3]] == [1, 1, 0]  # newest first


def test_login_history_endpoint_is_superadmin_only(env):
    login(env, "boss", "bosspassword")
    assert env.get("/api/login-history").status_code == 200

    env.post("/api/logout")
    login(env, "tma", "tmapassword")
    assert env.get("/api/login-history").status_code == 403


def test_login_history_requires_sign_in(env):
    assert env.get("/api/login-history").status_code == 401


def test_login_history_records_source_ip(env):
    # events are newest-first, so this must be the only login recorded here --
    # a second, header-less call would otherwise outrank it at events[0].
    login(env, "boss", "bosspassword", headers={"X-Forwarded-For": "203.0.113.7, 10.0.0.1"})
    events = auth.recent_login_events()
    assert events[0]["ip"] == "203.0.113.7"  # first (left-most) hop, the real client


def test_login_history_is_bounded(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "bound.db")
    db.init_db()
    auth.init_auth_schema()
    for i in range(auth.LOGIN_HISTORY_LIMIT + 25):
        auth.record_login_event("someone", True, "1.2.3.4")
    with db._connect() as conn:
        n = conn.execute("SELECT COUNT(*) FROM login_history").fetchone()[0]
    assert n == auth.LOGIN_HISTORY_LIMIT


# --- Sign out other devices --------------------------------------------------

def test_revoke_others_keeps_current_session_alive(env):
    login(env, "boss", "bosspassword")
    r = env.post("/api/sessions/revoke-others")
    assert r.status_code == 200
    assert env.get("/api/me").json()["signedIn"] is True


def test_revoke_others_ends_other_sessions(env):
    login(env, "boss", "bosspassword")
    other = fresh()
    login(other, "boss", "bosspassword")
    assert other.get("/api/me").json()["signedIn"] is True

    env.post("/api/sessions/revoke-others")
    assert other.get("/api/me").json()["signedIn"] is False
    assert env.get("/api/me").json()["signedIn"] is True


def test_revoke_others_does_not_touch_a_different_users_sessions(env):
    login(env, "boss", "bosspassword")
    other_user = fresh()
    login(other_user, "tma", "tmapassword")

    env.post("/api/sessions/revoke-others")
    assert other_user.get("/api/me").json()["signedIn"] is True


def test_revoke_others_requires_sign_in(env):
    assert env.post("/api/sessions/revoke-others").status_code == 401


# --- Weak password blocklist -------------------------------------------------

@pytest.mark.parametrize("weak", ["password1", "12345678", "superadmin", "aaaaaaaa"])
def test_common_passwords_rejected_on_create(env, weak):
    login(env, "boss", "bosspassword")
    r = env.post("/api/users", json={"username": "newbie", "password": weak, "role": "drafter"})
    assert r.status_code == 400
    assert auth.get_user_by_name("newbie") is None


def test_username_as_password_rejected(env):
    login(env, "boss", "bosspassword")
    r = env.post("/api/users", json={"username": "echoname", "password": "echoname", "role": "drafter"})
    assert r.status_code == 400


def test_reasonable_password_still_accepted(env):
    login(env, "boss", "bosspassword")
    r = env.post("/api/users", json={"username": "newbie2",
                                     "password": "correct-horse-battery",
                                     "role": "drafter"})
    assert r.status_code == 200


def test_weak_password_rejected_on_self_change(env):
    login(env, "dee", "deepassword")
    r = env.post("/api/password", json={"currentPassword": "deepassword",
                                        "newPassword": "password1"})
    assert r.status_code == 400
    assert auth.authenticate("dee", "deepassword") is not None  # unchanged


def test_is_weak_password_function_directly():
    assert auth.is_weak_password("password1") is not None
    assert auth.is_weak_password("aaaaaaaa") is not None
    assert auth.is_weak_password("boss", username="boss") is not None
    assert auth.is_weak_password("correct-horse-battery") is None


# --- Response headers --------------------------------------------------------

def test_new_security_headers_present(env):
    r = env.get("/")
    assert r.headers.get("Permissions-Policy")
    assert r.headers.get("Cross-Origin-Opener-Policy") == "same-origin"
    assert r.headers.get("Cross-Origin-Resource-Policy") == "same-origin"
    assert r.headers.get("X-Permitted-Cross-Domain-Policies") == "none"
    assert "max-age" in r.headers.get("Strict-Transport-Security", "")


def test_permissions_policy_blocks_sensitive_apis():
    pp = security.SECURITY_HEADERS["Permissions-Policy"]
    for capability in ("geolocation", "camera", "microphone"):
        assert capability + "=()" in pp
