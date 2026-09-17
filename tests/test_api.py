"""The HTTP surface: who may call what, and what the server does with it."""

import json

from backend import auth, db, roles, security
from conftest import sign_in

SIMPLE = {
    "clients": [{"id": "c-1", "name": "Nova Foods"}],
    "records": [{"id": "t-001", "clientId": "c-1", "ipType": "trademark",
                 "brand": "NOVA", "status": "filed", "assignedTo": "",
                 "timeline": [], "professionalFee": 25000}],
    "log": [],
    "nextClientSeq": 2,
    "nextRecordSeq": 2,
}


def seed(env, accounts):
    """Sign in as superadmin, store SIMPLE, sign out again."""
    sign_in(env, *accounts[roles.SUPERADMIN])
    assert env.put("/api/state", json=SIMPLE).status_code == 200
    env.post("/api/logout")


# --- Unauthenticated --------------------------------------------------------

def test_health_needs_no_session(env):
    assert env.get("/api/health").json() == {"status": "ok"}


def test_state_is_not_served_to_a_stranger(env, accounts):
    seed(env, accounts)
    body = env.get("/api/state").json()
    assert body["authorized"] is False
    assert body["state"] is None


def test_every_mutating_endpoint_refuses_a_stranger(env, accounts):
    assert env.put("/api/state", json=SIMPLE).status_code == 401
    assert env.get("/api/users").status_code == 401
    assert env.post("/api/users", json={}).status_code == 401
    assert env.delete("/api/users/1").status_code == 401
    assert env.patch("/api/users/1", json={}).status_code == 401
    assert env.post("/api/key/rotate", json={}).status_code == 401
    assert env.get("/api/assignees").status_code == 401
    assert env.get("/api/login-history").status_code == 401
    assert env.post("/api/sessions/revoke-others").status_code == 401


def test_me_reports_signed_out(env):
    assert env.get("/api/me").json() == {"signedIn": False}


# --- Identity ---------------------------------------------------------------

def test_me_reports_role_and_capabilities(env, accounts):
    sign_in(env, *accounts[roles.TRADEMARK_ADMIN])
    body = env.get("/api/me").json()
    assert body["signedIn"] is True
    assert body["username"] == "tma"
    assert body["role"] == roles.TRADEMARK_ADMIN
    assert body["roleLabel"] == "Trademark admin"
    assert "view_financials" not in body["can"]
    assert "create_matter" in body["can"]


def test_logout_ends_the_session(env, accounts):
    sign_in(env, *accounts[roles.DRAFTER])
    assert env.get("/api/me").json()["signedIn"] is True
    env.post("/api/logout")
    assert env.get("/api/me").json()["signedIn"] is False


def test_wrong_login_key_is_refused(env, accounts):
    r = env.post("/api/login", json={"key": "lx_" + "z" * 40})
    assert r.status_code == 401


# --- Key-header authentication (no session at all) -------------------------

def test_a_bearer_key_authenticates_without_a_session_cookie(env, accounts):
    _username, key = accounts[roles.TRADEMARK_ADMIN]
    r = env.get("/api/me", headers={"Authorization": "Bearer " + key})
    assert r.status_code == 200
    assert r.json()["signedIn"] is True
    assert r.json()["role"] == roles.TRADEMARK_ADMIN
    # No cookie was ever set by using the header form.
    assert "set-cookie" not in r.headers


def test_the_custom_key_header_also_works(env, accounts):
    _username, key = accounts[roles.DRAFTER]
    r = env.get("/api/me", headers={"X-Lextria-Key": key})
    assert r.status_code == 200 and r.json()["signedIn"] is True


def test_a_wrong_header_key_is_rejected_even_with_a_valid_cookie_present(env, accounts):
    """A caller presenting a key is asserting an identity; a bad key must not
    fall back to whatever cookie happens to be on the request."""
    sign_in(env, *accounts[roles.SUPERADMIN])  # sets a valid superadmin cookie
    r = env.get("/api/me", headers={"X-Lextria-Key": "lx_" + "q" * 40})
    assert r.status_code == 401


def test_a_suspended_accounts_key_stops_working_immediately(env, accounts):
    username, key = accounts[roles.DRAFTER]
    user = auth.get_user_by_name(username)
    auth.set_active(user["id"], False)
    r = env.get("/api/me", headers={"X-Lextria-Key": key})
    assert r.status_code == 401


# --- User administration ----------------------------------------------------

def test_only_a_superadmin_may_manage_users(env, accounts):
    for role in (roles.TRADEMARK_ADMIN, roles.DRAFTER):
        sign_in(env, *accounts[role])
        assert env.get("/api/users").status_code == 403
        assert env.post("/api/users", json={
            "username": "x", "role": roles.DRAFTER,
        }).status_code == 403
        assert env.get("/api/login-history").status_code == 403
        env.post("/api/logout")

    sign_in(env, *accounts[roles.SUPERADMIN])
    assert env.get("/api/users").status_code == 200


def test_creating_a_user_returns_a_key_exactly_once(env, accounts):
    sign_in(env, *accounts[roles.SUPERADMIN])
    r = env.post("/api/users", json={"username": "newbie", "role": roles.DRAFTER})
    assert r.status_code == 200
    body = r.json()
    assert auth.looks_like_key(body["key"])
    # And the key list never carries it again.
    assert body["key"] not in env.get("/api/users").text


def test_creating_a_user_rejects_an_unknown_role(env, accounts):
    sign_in(env, *accounts[roles.SUPERADMIN])
    r = env.post("/api/users", json={"username": "newbie", "role": "patent_admin"})
    assert r.status_code == 400


def test_creating_a_user_requires_a_username(env, accounts):
    sign_in(env, *accounts[roles.SUPERADMIN])
    r = env.post("/api/users", json={"username": "", "role": roles.DRAFTER})
    assert r.status_code == 400


def test_duplicate_username_is_a_conflict(env, accounts):
    sign_in(env, *accounts[roles.SUPERADMIN])
    r = env.post("/api/users", json={"username": "dee", "role": roles.DRAFTER})
    assert r.status_code == 409


def test_user_list_never_includes_the_key_hash(env, accounts):
    sign_in(env, *accounts[roles.SUPERADMIN])
    assert "key_hash" not in env.get("/api/users").text


def test_you_cannot_delete_or_demote_yourself(env, accounts):
    sign_in(env, *accounts[roles.SUPERADMIN])
    me = env.get("/api/users").json()["you"]
    assert env.delete("/api/users/%d" % me).status_code == 400
    assert env.patch("/api/users/%d" % me, json={"role": roles.DRAFTER}).status_code == 400


def test_the_last_superadmin_cannot_be_removed(env, accounts):
    """Otherwise the installation is left with nobody able to manage users or
    see financial data, recoverable only from the CLI."""
    sign_in(env, *accounts[roles.SUPERADMIN])
    boss2_key = env.post("/api/users",
                         json={"username": "boss2", "role": roles.SUPERADMIN}).json()["key"]
    users = {u["username"]: u["id"] for u in env.get("/api/users").json()["users"]}

    # boss2 may go: `boss` is still there.
    assert env.delete("/api/users/%d" % users["boss2"]).status_code == 200
    # Now demoting the only remaining one is refused.
    boss3_key = env.post("/api/users",
                         json={"username": "boss3", "role": roles.SUPERADMIN}).json()["key"]
    users = {u["username"]: u["id"] for u in env.get("/api/users").json()["users"]}
    sign_in(env, "boss3", boss3_key)
    r = env.patch("/api/users/%d" % users["boss"], json={"role": roles.DRAFTER})
    assert r.status_code == 200  # boss3 is still a superadmin, so this is fine
    r = env.delete("/api/users/%d" % users["boss"])
    assert r.status_code == 200
    assert boss2_key and boss3_key  # sanity: both keys really were issued


def test_suspending_a_drafter_clears_their_assignments(env, accounts):
    sign_in(env, *accounts[roles.SUPERADMIN])
    document = json.loads(json.dumps(SIMPLE))
    document["records"][0]["assignedTo"] = "dee"
    env.put("/api/state", json=document)

    users = {u["username"]: u["id"] for u in env.get("/api/users").json()["users"]}
    env.patch("/api/users/%d" % users["dee"], json={"active": False})

    stored = db.load_state()
    assert stored["records"][0]["assignedTo"] == ""


# --- Reissuing another account's key (super admin only) --------------------

def test_a_superadmin_can_reissue_someone_elses_key(env, accounts):
    sign_in(env, *accounts[roles.SUPERADMIN])
    users = {u["username"]: u["id"] for u in env.get("/api/users").json()["users"]}
    r = env.post("/api/users/%d/rotate-key" % users["dee"])
    assert r.status_code == 200
    new_key = r.json()["key"]

    # The old key from the fixture no longer works.
    _old_username, old_key = accounts[roles.DRAFTER]
    assert env.get("/api/me", headers={"X-Lextria-Key": old_key}).status_code == 401
    # The new one does.
    assert env.get("/api/me", headers={"X-Lextria-Key": new_key}).status_code == 200


def test_a_trademark_admin_cannot_reissue_keys(env, accounts):
    sign_in(env, *accounts[roles.TRADEMARK_ADMIN])
    r = env.post("/api/users/1/rotate-key")
    assert r.status_code == 403


def test_rotating_an_unknown_users_key_is_a_404(env, accounts):
    sign_in(env, *accounts[roles.SUPERADMIN])
    assert env.post("/api/users/999999/rotate-key").status_code == 404


# --- Rotating your own key --------------------------------------------------

def test_rotating_your_own_key_returns_the_new_one_and_keeps_this_session(env, accounts):
    sign_in(env, *accounts[roles.DRAFTER])
    r = env.post("/api/key/rotate")
    assert r.status_code == 200
    new_key = r.json()["key"]
    assert auth.looks_like_key(new_key)
    # Still signed in via the cookie -- a fresh one was issued.
    assert env.get("/api/me").json()["signedIn"] is True


def test_the_old_key_stops_working_after_rotation(env, accounts):
    _username, old_key = accounts[roles.DRAFTER]
    sign_in(env, "dee", old_key)
    env.post("/api/key/rotate")
    assert env.get("/api/me", headers={"X-Lextria-Key": old_key}).status_code == 401


def test_rotating_via_the_header_form_issues_no_cookie(env, accounts):
    _username, key = accounts[roles.DRAFTER]
    r = env.post("/api/key/rotate", headers={"X-Lextria-Key": key})
    assert r.status_code == 200
    assert "set-cookie" not in r.headers


# --- Assignees --------------------------------------------------------------

def test_a_trademark_admin_may_list_assignees_but_not_users(env, accounts):
    """Assigning work must not require the power to manage accounts."""
    sign_in(env, *accounts[roles.TRADEMARK_ADMIN])
    assert env.get("/api/users").status_code == 403
    body = env.get("/api/assignees")
    assert body.status_code == 200
    assert {a["username"] for a in body.json()["assignees"]} == {"boss", "tma", "dee"}
    assert "key_hash" not in body.text


def test_a_drafter_may_not_list_assignees(env, accounts):
    sign_in(env, *accounts[roles.DRAFTER])
    assert env.get("/api/assignees").status_code == 403


# --- The ledger -------------------------------------------------------------

def test_first_load_reports_no_state_so_the_page_uses_its_seed(env, accounts):
    sign_in(env, *accounts[roles.SUPERADMIN])
    body = env.get("/api/state").json()
    assert body["state"] is None
    assert body["revision"] == 0


def test_revision_advances_on_each_save(env, accounts):
    sign_in(env, *accounts[roles.SUPERADMIN])
    assert env.put("/api/state", json=SIMPLE).json()["revision"] == 1
    assert env.put("/api/state", json=SIMPLE).json()["revision"] == 2
    assert env.get("/api/state").json()["revision"] == 2


def test_malformed_and_non_object_bodies_are_rejected(env, accounts):
    sign_in(env, *accounts[roles.SUPERADMIN])
    assert env.put("/api/state", content=b"{not json").status_code == 400
    assert env.put("/api/state", json=[1, 2, 3]).status_code == 400
    assert env.post("/api/login", content=b"////").status_code == 400


def test_an_oversized_ledger_is_refused(env, accounts):
    sign_in(env, *accounts[roles.SUPERADMIN])
    huge = b'{"records": "' + b"x" * (security.MAX_BODY_BYTES + 100) + b'"}'
    assert env.put("/api/state", content=huge).status_code == 413


def test_a_drafters_save_cannot_wipe_the_ledger(env, accounts):
    """The end-to-end version of the merge rule: a filtered read, written back
    literally, would delete every matter the drafter could not see."""
    sign_in(env, *accounts[roles.SUPERADMIN])
    document = json.loads(json.dumps(SIMPLE))
    document["records"].append({"id": "t-002", "clientId": "c-1",
                                "ipType": "copyright", "brand": "Hidden work",
                                "status": "cr_filed", "assignedTo": "", "timeline": []})
    env.put("/api/state", json=document)
    env.post("/api/logout")

    sign_in(env, *accounts[roles.DRAFTER])
    mine = env.get("/api/state").json()["state"]
    assert mine["records"] == []          # nothing is assigned to dee
    env.put("/api/state", json=mine)      # save that back verbatim

    assert len(db.load_state()["records"]) == 2


def test_concurrent_saves_do_not_revert_each_other(env, accounts):
    """Two admins editing different matters from the same starting point."""
    sign_in(env, *accounts[roles.SUPERADMIN])
    document = json.loads(json.dumps(SIMPLE))
    document["records"].append({"id": "t-002", "clientId": "c-1",
                                "ipType": "copyright", "brand": "Second",
                                "status": "cr_filed", "assignedTo": "", "timeline": []})
    revision = env.put("/api/state", json=document).json()["revision"]

    first = json.loads(json.dumps(document))
    first["records"][0]["brand"] = "NOVA EDITED"
    env.put("/api/state", json=first, headers={"X-Ledger-Revision": str(revision)})

    # The second save is based on the SAME revision -- it never saw the edit above.
    second = json.loads(json.dumps(document))
    second["records"][1]["brand"] = "Second EDITED"
    env.put("/api/state", json=second, headers={"X-Ledger-Revision": str(revision)})

    stored = {r["id"]: r["brand"] for r in db.load_state()["records"]}
    assert stored["t-001"] == "NOVA EDITED"    # not reverted by the later save
    assert stored["t-002"] == "Second EDITED"


def test_two_matters_created_at_once_both_survive(env, accounts):
    sign_in(env, *accounts[roles.SUPERADMIN])
    revision = env.put("/api/state", json=SIMPLE).json()["revision"]

    first = json.loads(json.dumps(SIMPLE))
    first["records"].append({"id": "t-002", "clientId": "c-1", "ipType": "trademark",
                             "brand": "Mine", "status": "filed", "timeline": []})
    env.put("/api/state", json=first, headers={"X-Ledger-Revision": str(revision)})

    # Same id, different matter, from someone who never saw the save above.
    second = json.loads(json.dumps(SIMPLE))
    second["records"].append({"id": "t-002", "clientId": "c-1", "ipType": "copyright",
                              "brand": "Theirs", "status": "cr_filed", "timeline": []})
    body = env.put("/api/state", json=second,
                   headers={"X-Ledger-Revision": str(revision)}).json()

    brands = {r["brand"] for r in db.load_state()["records"]}
    assert {"Mine", "Theirs"} <= brands
    assert body["idRemap"]["records"]["t-002"] != "t-002"


def test_log_entries_are_attributed_to_the_session_not_the_payload(env, accounts):
    sign_in(env, *accounts[roles.SUPERADMIN])
    env.put("/api/state", json=SIMPLE)
    env.post("/api/logout")

    sign_in(env, *accounts[roles.TRADEMARK_ADMIN])
    document = env.get("/api/state").json()["state"]
    document["log"] = [{"ts": "1999-01-01T00:00:00+00:00",
                        "summary": "Did a thing", "by": "boss"}]
    env.put("/api/state", json=document)

    entry = db.load_state()["log"][0]
    assert entry["by"] == "tma"              # not the claimed author
    assert not entry["ts"].startswith("1999")  # not the claimed time


def test_ledger_writes_via_the_bearer_header_work_without_a_session(env, accounts):
    """A script identifies itself with a key on every call, no cookie needed."""
    _username, key = accounts[roles.SUPERADMIN]
    r = env.put("/api/state", json=SIMPLE, headers={"Authorization": "Bearer " + key})
    assert r.status_code == 200


# --- Hardening --------------------------------------------------------------

def test_a_domain_name_host_header_is_refused(env, accounts):
    """The DNS-rebinding guard: a real client never arrives as a domain name."""
    r = env.get("/api/health", headers={"Host": "evil.example.com"})
    assert r.status_code == 421


def test_localhost_and_bare_ip_hosts_are_accepted(env):
    for host in ("localhost", "localhost:8000", "127.0.0.1", "127.0.0.1:8000",
                 "[::1]", "[::1]:8000", "192.168.1.20:8000"):
        assert security.host_is_safe(host), host
    for host in ("", "evil.example.com", "lextria.example.com:8000"):
        assert not security.host_is_safe(host), host


def test_security_headers_are_present(env):
    headers = env.get("/api/health").headers
    assert headers["X-Content-Type-Options"] == "nosniff"
    assert headers["X-Frame-Options"] == "DENY"
    assert headers["Referrer-Policy"] == "no-referrer"
    assert headers["Cache-Control"] == "no-store"
    assert "frame-ancestors 'none'" in headers["Content-Security-Policy"]


def test_the_page_is_served_with_a_matching_script_nonce(env):
    """The inline app bundle runs only because the server stamped this exact
    value into both the page and the header."""
    response = env.get("/")
    assert response.status_code == 200
    policy = response.headers["Content-Security-Policy"]
    nonce = policy.split("'nonce-")[1].split("'")[0]
    assert 'nonce="%s"' % nonce in response.text
    assert "unsafe-inline" not in policy.split("style-src")[0]


def test_each_response_gets_a_fresh_nonce(env):
    first = env.get("/").headers["Content-Security-Policy"]
    second = env.get("/").headers["Content-Security-Policy"]
    assert first != second
