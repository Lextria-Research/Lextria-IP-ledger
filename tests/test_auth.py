"""Access keys, sessions and rate limiting."""

from backend import auth, roles
from conftest import sign_in


# --- Keys ---------------------------------------------------------------

def test_generated_keys_are_unique_and_well_formed():
    keys = {auth.generate_key() for _ in range(50)}
    assert len(keys) == 50
    for k in keys:
        assert k.startswith(auth.KEY_PREFIX)
        assert len(k) > 20


def test_key_hash_is_deterministic_but_the_key_is_not_recoverable():
    key = auth.generate_key()
    h1 = auth.hash_key(key)
    h2 = auth.hash_key(key)
    assert h1 == h2
    assert key not in h1


def test_key_hint_never_contains_the_whole_key():
    key = auth.generate_key()
    hint = auth.key_hint(key)
    assert hint != key
    assert len(hint) < len(key)
    assert hint.startswith(auth.KEY_PREFIX)


def test_looks_like_key_rejects_junk():
    assert not auth.looks_like_key(None)
    assert not auth.looks_like_key("")
    assert not auth.looks_like_key("not-a-key")
    assert not auth.looks_like_key("lx_short")
    assert auth.looks_like_key(auth.generate_key())


# --- Accounts -------------------------------------------------------------

def test_creating_a_user_returns_the_key_exactly_once(env):
    user_id, key = auth.create_user("rakesh", roles.DRAFTER)
    assert user_id is not None
    assert auth.looks_like_key(key)
    # The stored record never carries the key itself.
    stored = auth.list_users()[0]
    assert "key_hash" not in stored
    assert key not in str(stored)


def test_usernames_are_unique_case_insensitively(env):
    assert auth.create_user("Rakesh", roles.DRAFTER)[0] is not None
    assert auth.create_user("rakesh", roles.DRAFTER) == (None, None)


def test_suspended_account_cannot_authenticate(env, accounts):
    username, key = accounts[roles.DRAFTER]
    user = auth.get_user_by_name(username)
    auth.set_active(user["id"], False)
    assert auth.authenticate_key(key) is None


def test_unknown_role_is_refused(env):
    try:
        auth.create_user("x", "patent_admin")
    except ValueError as exc:
        assert "unknown role" in str(exc)
    else:
        raise AssertionError("expected ValueError")


def test_count_active_superadmins_ignores_suspended_and_excluded(env, accounts):
    boss = auth.get_user_by_name("boss")
    assert auth.count_active_superadmins() == 1
    assert auth.count_active_superadmins(excluding_id=boss["id"]) == 0
    auth.set_active(boss["id"], False)
    assert auth.count_active_superadmins() == 0


# --- Authentication ---------------------------------------------------------

def test_authenticate_key_round_trip(env, accounts):
    username, key = accounts[roles.DRAFTER]
    user = auth.authenticate_key(key)
    assert user is not None
    assert user["username"] == username
    assert user["role"] == roles.DRAFTER


def test_authenticate_key_rejects_wrong_or_junk_keys(env, accounts):
    assert auth.authenticate_key("lx_" + "x" * 40) is None
    assert auth.authenticate_key("not-a-key-at-all") is None
    assert auth.authenticate_key(None) is None
    assert auth.authenticate_key("") is None


def test_rotating_a_key_invalidates_the_old_one(env, accounts):
    username, old_key = accounts[roles.DRAFTER]
    user = auth.get_user_by_name(username)
    new_key = auth.rotate_key(user["id"])
    assert auth.authenticate_key(old_key) is None
    assert auth.authenticate_key(new_key)["username"] == username


def test_rotating_a_key_ends_existing_sessions(env, accounts):
    username, _key = accounts[roles.DRAFTER]
    user = auth.get_user_by_name(username)
    token = auth.start_session(user["id"])
    auth.rotate_key(user["id"])
    assert auth.session_user(token) is None


def test_rotate_key_on_unknown_account_returns_none(env):
    assert auth.rotate_key(999999) is None


# --- Sessions ---------------------------------------------------------------

def test_session_round_trip(env, accounts):
    username, _key = accounts[roles.DRAFTER]
    user = auth.get_user_by_name(username)
    token = auth.start_session(user["id"])
    assert auth.session_user(token)["username"] == username
    auth.end_session(token)
    assert auth.session_user(token) is None


def test_session_user_rejects_junk(env):
    assert auth.session_user(None) is None
    assert auth.session_user("") is None
    assert auth.session_user("not-a-real-token") is None


def test_suspending_an_account_ends_its_sessions(env, accounts):
    username, _key = accounts[roles.DRAFTER]
    user = auth.get_user_by_name(username)
    token = auth.start_session(user["id"])
    auth.set_active(user["id"], False)
    assert auth.session_user(token) is None


def test_changing_a_role_ends_sessions(env, accounts):
    """The role is baked into the session's view; an open session would keep the
    old permissions until it expired."""
    username, _key = accounts[roles.DRAFTER]
    user = auth.get_user_by_name(username)
    token = auth.start_session(user["id"])
    auth.set_role(user["id"], roles.TRADEMARK_ADMIN)
    assert auth.session_user(token) is None


def test_revoke_others_keeps_the_calling_session(env, accounts):
    username, _key = accounts[roles.DRAFTER]
    user = auth.get_user_by_name(username)
    keep = auth.start_session(user["id"])
    drop = auth.start_session(user["id"])
    auth.end_other_sessions(user["id"], keep)
    assert auth.session_user(keep) is not None
    assert auth.session_user(drop) is None


def test_session_cookie_is_httponly_and_samesite_strict(env, accounts):
    response = sign_in(env, *accounts[roles.DRAFTER])
    header = response.headers["set-cookie"]
    assert auth.SESSION_COOKIE in header
    assert "HttpOnly" in header
    assert "SameSite=strict" in header.replace("SameSite=Strict", "SameSite=strict")


# --- Rate limiting -----------------------------------------------------------

def test_per_address_limit_covers_repeated_guesses(env, accounts):
    auth.reset_ip_limiter()
    allowed = 0
    for _ in range(auth.IP_MAX_ATTEMPTS):
        if auth.ip_wait_seconds("198.51.100.9") == 0:
            auth.record_ip_attempt("198.51.100.9")
            allowed += 1
    assert allowed == auth.IP_MAX_ATTEMPTS
    assert auth.ip_wait_seconds("198.51.100.9") > 0
    # A different address is unaffected.
    assert auth.ip_wait_seconds("198.51.100.10") == 0


def test_login_endpoint_returns_429_once_the_address_is_limited(env, accounts):
    for _ in range(auth.IP_MAX_ATTEMPTS):
        sign_in(env, "whoever", "lx_" + "x" * 40)
    assert sign_in(env, "whoever", "lx_" + "y" * 40).status_code == 429


def test_login_failure_does_not_reveal_which_accounts_exist(env, accounts):
    real_account_key = "lx_" + "x" * 40  # syntactically valid, but not issued
    other_key = "lx_" + "y" * 40
    r1 = sign_in(env, "dee", real_account_key)
    r2 = sign_in(env, "nobody", other_key)
    assert r1.status_code == r2.status_code == 401
    assert r1.json()["error"] == r2.json()["error"]


# --- Login history ----------------------------------------------------------

def test_login_history_records_success_and_failure(env, accounts):
    username, key = accounts[roles.DRAFTER]
    sign_in(env, username, "lx_" + "z" * 40)
    sign_in(env, username, key)
    events = auth.recent_login_events()
    assert [e["success"] for e in events[:2]] == [1, 0]
    assert events[0]["username"] == username
    assert events[1]["username"] == auth.UNKNOWN_KEY


def test_login_history_never_stores_the_key(env, accounts):
    username, key = accounts[roles.DRAFTER]
    sign_in(env, username, key)
    assert all(key not in str(e) for e in auth.recent_login_events())
