"""Regression tests for the ten defects found in the full audit.

Each test here reproduces a specific defect that was confirmed present against
a running server, so none of them can quietly come back.
"""

import pathlib
import sqlite3
import sys

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from backend import auth, db, roles  # noqa: E402


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "hard.db")
    from backend.main import app
    with TestClient(app, base_url="http://localhost") as c:
        auth.create_user("boss", "bosspassword", roles.SUPERADMIN)
        auth.create_user("tma", "tmapassword", roles.TRADEMARK_ADMIN)
        auth.create_user("dee", "deepassword", roles.DRAFTER)
        yield c


def login(c, u, p):
    return c.post("/api/login", json={"username": u, "password": p})


LEDGER = {
    "clients": [{"id": "c-1", "name": "Acme"}],
    "records": [{"id": "t-1", "clientId": "c-1", "ipType": "trademark",
                 "brand": "ACMEBRAND", "appno": "TM-1", "status": "filed",
                 "assignedTo": "dee", "timeline": [],
                 "professionalFee": "15000"}],
    "log": [{"ts": "2026-01-01T00:00:00+00:00", "summary": "seeded"}],
    "settings": {"loginEnabled": False, "loginHash": "original-hash"},
    "nextClientSeq": 2, "nextRecordSeq": 2,
}


def seed(c):
    login(c, "boss", "bosspassword")
    assert c.put("/api/state", json=LEDGER).status_code == 200
    c.post("/api/logout")


# --- Defect 8: connections were never closed --------------------------------

def test_connection_is_closed_after_use(tmp_path, monkeypatch):
    """`with sqlite3.connect(...)` commits but does NOT close."""
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "close.db")
    db.init_db()
    with db._connect() as conn:
        conn.execute("SELECT 1")
    with pytest.raises(sqlite3.ProgrammingError):
        conn.execute("SELECT 1")


def test_failed_transaction_rolls_back(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "rb.db")
    db.init_db()
    with pytest.raises(RuntimeError):
        with db._connect() as conn:
            conn.execute("INSERT INTO ledger_state (id, document, revision, updated_at)"
                         " VALUES (1, 'x', 1, 't')")
            raise RuntimeError("boom")
    with db._connect() as conn:
        assert conn.execute("SELECT COUNT(*) FROM ledger_state").fetchone()[0] == 0


# --- Defect 1: password reset left sessions alive ---------------------------

def test_password_reset_invalidates_sessions(env, tmp_path):
    from backend.main import app
    victim = TestClient(app, base_url="http://localhost")
    login(victim, "tma", "tmapassword")
    assert victim.get("/api/me").json()["signedIn"] is True

    auth.set_password("tma", "a-brand-new-password")
    assert victim.get("/api/me").json()["signedIn"] is False


def test_deleting_a_user_invalidates_their_session(env):
    from backend.main import app
    doomed = TestClient(app, base_url="http://localhost")
    login(doomed, "dee", "deepassword")
    auth.delete_user(auth.get_user_by_name("dee")["id"])
    assert doomed.get("/api/me").json().get("signedIn") is False


# --- Defect 2: malformed JSON crashed the handler ---------------------------

@pytest.mark.parametrize("body", [b"{not json", b"", b"[1,2,3]", b'"a string"'])
def test_login_rejects_bad_bodies_without_crashing(env, body):
    r = env.post("/api/login", content=body,
                 headers={"Content-Type": "application/json"})
    assert r.status_code == 400


def test_add_user_rejects_bad_body_without_crashing(env):
    login(env, "boss", "bosspassword")
    r = env.post("/api/users", content=b"{bad",
                 headers={"Content-Type": "application/json"})
    assert r.status_code == 400


# --- Defect 3: no brute-force protection ------------------------------------

def test_repeated_failures_lock_the_account(env):
    codes = [env.post("/api/login",
                      json={"username": "boss", "password": "wrong"}).status_code
             for _ in range(auth.MAX_FAILURES + 3)]
    assert 429 in codes, "no lockout after %d failures" % auth.MAX_FAILURES


def test_lockout_blocks_even_the_correct_password(env):
    for _ in range(auth.MAX_FAILURES + 1):
        env.post("/api/login", json={"username": "boss", "password": "wrong"})
    assert login(env, "boss", "bosspassword").status_code == 429


def test_successful_login_clears_the_failure_count(env):
    for _ in range(auth.MAX_FAILURES - 1):
        env.post("/api/login", json={"username": "boss", "password": "wrong"})
    assert login(env, "boss", "bosspassword").status_code == 200
    assert auth.lockout_seconds_remaining("boss") == 0


def test_lockout_is_per_account(env):
    for _ in range(auth.MAX_FAILURES + 1):
        env.post("/api/login", json={"username": "boss", "password": "wrong"})
    # A different user must not be collateral damage.
    assert login(env, "tma", "tmapassword").status_code == 200


# --- Defects 4 and 5: forging history ---------------------------------------

def test_drafter_cannot_forge_the_matter_timeline(env):
    seed(env)
    login(env, "dee", "deepassword")
    doc = env.get("/api/state").json()["state"]
    doc["records"][0]["timeline"] = [{"id": "forged", "toStatus": "registered",
                                      "remarks": "FABRICATED",
                                      "timestamp": "2020-01-01T00:00:00Z"}]
    env.put("/api/state", json=doc)

    env.post("/api/logout")
    login(env, "boss", "bosspassword")
    tl = env.get("/api/state").json()["state"]["records"][0]["timeline"]
    assert not any(e.get("remarks") == "FABRICATED" for e in tl)


def test_drafter_status_change_still_produces_a_timeline_entry(env):
    """Blocking forgery must not stop legitimate history being recorded."""
    seed(env)
    login(env, "dee", "deepassword")
    doc = env.get("/api/state").json()["state"]
    doc["records"][0]["status"] = "objected"
    env.put("/api/state", json=doc)

    env.post("/api/logout")
    login(env, "boss", "bosspassword")
    tl = env.get("/api/state").json()["state"]["records"][0]["timeline"]
    assert len(tl) == 1
    assert tl[0]["fromStatus"] == "filed"
    assert tl[0]["toStatus"] == "objected"
    assert tl[0]["by"] == "dee"            # attributed
    assert tl[0]["serverGenerated"] is True


def test_drafter_cannot_backdate_or_misattribute_log_entries(env):
    seed(env)
    login(env, "dee", "deepassword")
    doc = env.get("/api/state").json()["state"]
    doc["log"] = [{"ts": "1999-01-01T00:00:00+00:00", "summary": "SNEAKY",
                   "by": "boss"}]
    env.put("/api/state", json=doc)

    env.post("/api/logout")
    login(env, "boss", "bosspassword")
    entries = env.get("/api/state").json()["state"]["log"]
    sneaky = [e for e in entries if e.get("summary") == "SNEAKY"]
    if sneaky:
        assert sneaky[0]["ts"] != "1999-01-01T00:00:00+00:00", "timestamp not re-stamped"
        assert sneaky[0]["by"] == "dee", "author not corrected to the real user"


def test_log_entries_are_attributed(env):
    seed(env)
    login(env, "tma", "tmapassword")
    doc = env.get("/api/state").json()["state"]
    doc["log"] = [{"ts": "2026-05-05T00:00:00+00:00", "summary": "tma did a thing"}]
    env.put("/api/state", json=doc)

    env.post("/api/logout")
    login(env, "boss", "bosspassword")
    entries = env.get("/api/state").json()["state"]["log"]
    mine = [e for e in entries if e["summary"] == "tma did a thing"]
    assert mine and mine[0]["by"] == "tma"


def test_a_single_save_cannot_flood_the_log(env):
    seed(env)
    login(env, "tma", "tmapassword")
    doc = env.get("/api/state").json()["state"]
    doc["log"] = [{"ts": "2026-01-02T00:00:00+00:00", "summary": "spam %d" % i}
                  for i in range(200)]
    env.put("/api/state", json=doc)

    env.post("/api/logout")
    login(env, "boss", "bosspassword")
    entries = env.get("/api/state").json()["state"]["log"]
    spam = [e for e in entries if str(e.get("summary", "")).startswith("spam ")]
    assert len(spam) <= roles.MAX_NEW_LOG_ENTRIES


# --- Defect 6: trademark admin could overwrite ledger settings --------------

def test_trademark_admin_cannot_overwrite_settings(env):
    seed(env)
    login(env, "tma", "tmapassword")
    doc = env.get("/api/state").json()["state"]
    doc["settings"] = {"loginEnabled": True, "loginHash": "attacker-controlled"}
    env.put("/api/state", json=doc)

    env.post("/api/logout")
    login(env, "boss", "bosspassword")
    settings = env.get("/api/state").json()["state"]["settings"]
    assert settings["loginHash"] == "original-hash"


def test_drafter_cannot_overwrite_settings(env):
    seed(env)
    login(env, "dee", "deepassword")
    doc = env.get("/api/state").json()["state"]
    doc["settings"] = {"loginEnabled": True, "loginHash": "attacker-controlled"}
    env.put("/api/state", json=doc)

    env.post("/api/logout")
    login(env, "boss", "bosspassword")
    assert env.get("/api/state").json()["state"]["settings"]["loginHash"] == "original-hash"


def test_superadmin_can_still_change_settings(env):
    seed(env)
    login(env, "boss", "bosspassword")
    doc = env.get("/api/state").json()["state"]
    doc["settings"] = {"loginEnabled": True, "loginHash": "chosen-by-boss"}
    env.put("/api/state", json=doc)
    assert env.get("/api/state").json()["state"]["settings"]["loginHash"] == "chosen-by-boss"


# --- Defect 7: cookie Secure flag -------------------------------------------

def test_cookie_not_secure_over_plain_http(env):
    """Marking it Secure on http://localhost would stop the browser storing it."""
    r = login(env, "boss", "bosspassword")
    assert "secure" not in r.headers["set-cookie"].lower()


def test_cookie_is_secure_behind_an_https_proxy(env):
    r = env.post("/api/login",
                 json={"username": "boss", "password": "bosspassword"},
                 headers={"X-Forwarded-Proto": "https"})
    assert "secure" in r.headers["set-cookie"].lower()
