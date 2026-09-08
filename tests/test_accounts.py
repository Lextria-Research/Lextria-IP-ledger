"""Tests for self-service password change, suspend/restore and assignee lookup."""

import pathlib
import sys

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from backend import auth, db, roles  # noqa: E402


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "acct.db")
    from backend.main import app
    with TestClient(app, base_url="http://localhost") as c:
        auth.create_user("boss", "bosspassword", roles.SUPERADMIN)
        auth.create_user("tma", "tmapassword", roles.TRADEMARK_ADMIN)
        auth.create_user("dee", "deepassword", roles.DRAFTER)
        yield c


def login(c, u, p):
    return c.post("/api/login", json={"username": u, "password": p})


def fresh(app):
    return TestClient(app, base_url="http://localhost")


# --- Self-service password change -------------------------------------------

def test_can_change_own_password(env):
    login(env, "dee", "deepassword")
    r = env.post("/api/password", json={"currentPassword": "deepassword",
                                        "newPassword": "a-much-better-one"})
    assert r.status_code == 200
    assert auth.authenticate("dee", "a-much-better-one") is not None
    assert auth.authenticate("dee", "deepassword") is None


def test_wrong_current_password_is_refused(env):
    login(env, "dee", "deepassword")
    r = env.post("/api/password", json={"currentPassword": "not-it",
                                        "newPassword": "a-much-better-one"})
    assert r.status_code == 403
    assert auth.authenticate("dee", "deepassword") is not None


def test_short_new_password_refused(env):
    login(env, "dee", "deepassword")
    assert env.post("/api/password", json={"currentPassword": "deepassword",
                                           "newPassword": "short"}).status_code == 400


def test_changing_password_keeps_you_signed_in(env):
    """set_password ends every session; the current tab must get a fresh one."""
    login(env, "dee", "deepassword")
    env.post("/api/password", json={"currentPassword": "deepassword",
                                    "newPassword": "a-much-better-one"})
    assert env.get("/api/me").json()["signedIn"] is True


def test_changing_password_signs_out_other_devices(env):
    from backend.main import app
    other = fresh(app)
    login(other, "dee", "deepassword")
    assert other.get("/api/me").json()["signedIn"] is True

    login(env, "dee", "deepassword")
    env.post("/api/password", json={"currentPassword": "deepassword",
                                    "newPassword": "a-much-better-one"})
    assert other.get("/api/me").json()["signedIn"] is False


def test_password_change_requires_sign_in(env):
    assert env.post("/api/password", json={"currentPassword": "x",
                                           "newPassword": "yyyyyyyy"}).status_code == 401


# --- Suspend / restore ------------------------------------------------------

def test_superadmin_can_suspend_an_account(env):
    login(env, "boss", "bosspassword")
    uid = auth.get_user_by_name("dee")["id"]
    assert env.patch("/api/users/%d" % uid, json={"active": False}).status_code == 200
    assert auth.authenticate("dee", "deepassword") is None


def test_suspending_ends_that_users_session(env):
    from backend.main import app
    victim = fresh(app)
    login(victim, "dee", "deepassword")
    login(env, "boss", "bosspassword")
    env.patch("/api/users/%d" % auth.get_user_by_name("dee")["id"], json={"active": False})
    assert victim.get("/api/me").json().get("signedIn") is False


def test_restoring_an_account_works(env):
    login(env, "boss", "bosspassword")
    uid = auth.get_user_by_name("dee")["id"]
    env.patch("/api/users/%d" % uid, json={"active": False})
    env.patch("/api/users/%d" % uid, json={"active": True})
    assert auth.authenticate("dee", "deepassword") is not None


def test_cannot_suspend_yourself(env):
    """Otherwise an installation can end up with nobody able to manage users."""
    login(env, "boss", "bosspassword")
    uid = auth.get_user_by_name("boss")["id"]
    assert env.patch("/api/users/%d" % uid, json={"active": False}).status_code == 400
    assert auth.authenticate("boss", "bosspassword") is not None


def test_role_change_ends_the_old_session(env):
    from backend.main import app
    subject = fresh(app)
    login(subject, "dee", "deepassword")
    login(env, "boss", "bosspassword")
    env.patch("/api/users/%d" % auth.get_user_by_name("dee")["id"],
              json={"role": roles.TRADEMARK_ADMIN})
    # The old session carried the old role, so it must not survive.
    assert subject.get("/api/me").json().get("signedIn") is False
    assert auth.get_user_by_name("dee")["role"] == roles.TRADEMARK_ADMIN


def test_non_superadmin_cannot_suspend(env):
    login(env, "tma", "tmapassword")
    uid = auth.get_user_by_name("dee")["id"]
    assert env.patch("/api/users/%d" % uid, json={"active": False}).status_code == 403


def test_unknown_role_refused(env):
    login(env, "boss", "bosspassword")
    uid = auth.get_user_by_name("dee")["id"]
    assert env.patch("/api/users/%d" % uid, json={"role": "god"}).status_code == 400


# --- Assignee lookup --------------------------------------------------------

def test_trademark_admin_can_list_assignees(env):
    """Assigning work must not require the ability to manage accounts."""
    login(env, "tma", "tmapassword")
    r = env.get("/api/assignees")
    assert r.status_code == 200
    names = {a["username"] for a in r.json()["assignees"]}
    # The bootstrap "superadmin" account is present too, so check containment.
    assert {"boss", "tma", "dee"} <= names
    assert all(a["roleLabel"] for a in r.json()["assignees"])


def test_assignees_exposes_no_password_data(env):
    login(env, "boss", "bosspassword")
    body = env.get("/api/assignees").text
    assert "password" not in body.lower()
    assert "pbkdf2" not in body.lower()


def test_suspended_accounts_are_not_offered_as_assignees(env):
    login(env, "boss", "bosspassword")
    env.patch("/api/users/%d" % auth.get_user_by_name("dee")["id"], json={"active": False})
    names = {a["username"] for a in env.get("/api/assignees").json()["assignees"]}
    assert "dee" not in names


def test_drafter_cannot_list_assignees(env):
    login(env, "dee", "deepassword")
    assert env.get("/api/assignees").status_code == 403


def test_assignees_requires_sign_in(env):
    assert env.get("/api/assignees").status_code == 401
