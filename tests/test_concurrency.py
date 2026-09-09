"""Regression tests for the concurrency and integrity defects found in the
fourth audit pass: lost concurrent edits, colliding record/client ids on
concurrent creates, unguarded bulk-delete, and unvalidated assignment.

Each test reproduces a scenario that was confirmed broken against a running
server before roles.merge_for_role became a three-way merge.
"""

import pathlib
import sys

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from backend import auth, db, roles  # noqa: E402


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "conc.db")
    from backend.main import app
    with TestClient(app, base_url="http://localhost") as c:
        auth.create_user("boss", "bosspassword", roles.SUPERADMIN)
        auth.create_user("tma", "tmapassword", roles.TRADEMARK_ADMIN)
        auth.create_user("dee", "deepassword", roles.DRAFTER)
        yield c


def fresh():
    from backend.main import app
    return TestClient(app, base_url="http://localhost")


def login(c, u, p):
    r = c.post("/api/login", json={"username": u, "password": p})
    assert r.status_code == 200, r.text
    return r


def get_state_and_rev(c):
    r = c.get("/api/state")
    return r.json()["state"], r.json()["revision"]


def put_with_revision(c, doc, revision):
    return c.put("/api/state", json=doc, headers={"X-Ledger-Revision": str(revision)})


SEED = {
    "clients": [{"id": "c-1", "name": "Acme"}],
    "records": [
        {"id": "t-001", "clientId": "c-1", "ipType": "trademark",
         "brand": "A", "appno": "TM-1", "status": "filed", "assignedTo": "dee"},
        {"id": "t-002", "clientId": "c-1", "ipType": "trademark",
         "brand": "B", "appno": "TM-2", "status": "filed", "assignedTo": "tma"},
    ],
    "log": [], "nextClientSeq": 2, "nextRecordSeq": 3,
}


def seed(c):
    login(c, "boss", "bosspassword")
    assert put_with_revision(c, SEED, 0).status_code == 200
    c.post("/api/logout")


# --- Concurrent edits to different records: neither should be lost ---------

def test_concurrent_edits_to_different_records_both_survive(env):
    seed(env)
    a = fresh()
    b = fresh()
    login(a, "boss", "bosspassword")
    login(b, "tma", "tmapassword")

    doc_a, rev_a = get_state_and_rev(a)
    doc_b, rev_b = get_state_and_rev(b)
    assert rev_a == rev_b

    doc_a["records"][0]["brand"] = "EDITED-BY-A"
    doc_b["records"][1]["brand"] = "EDITED-BY-B"

    assert put_with_revision(a, doc_a, rev_a).status_code == 200
    assert put_with_revision(b, doc_b, rev_b).status_code == 200

    final, _ = get_state_and_rev(a)
    brands = {r["id"]: r["brand"] for r in final["records"]}
    assert brands["t-001"] == "EDITED-BY-A"
    assert brands["t-002"] == "EDITED-BY-B"


def test_concurrent_edit_without_revision_header_keeps_legacy_behavior(env):
    """No X-Ledger-Revision at all must behave exactly as before this feature."""
    seed(env)
    a = fresh()
    b = fresh()
    login(a, "boss", "bosspassword")
    login(b, "tma", "tmapassword")

    doc_a = a.get("/api/state").json()["state"]
    doc_b = b.get("/api/state").json()["state"]
    doc_a["records"][0]["brand"] = "EDITED-BY-A"
    doc_b["records"][1]["brand"] = "EDITED-BY-B"

    a.put("/api/state", json=doc_a)     # no header -> legacy, best-effort merge
    b.put("/api/state", json=doc_b)

    final = a.get("/api/state").json()["state"]
    brands = {r["id"]: r["brand"] for r in final["records"]}
    # Without a baseline the server cannot tell staleness apart from intent,
    # so B's full record list (including its unedited, stale copy of t-001)
    # applies on top -- documented limitation of not sending a revision.
    assert brands["t-002"] == "EDITED-BY-B"


# --- Concurrent creates that land on the same id: neither should vanish ----

def test_concurrent_new_matters_both_survive_even_with_colliding_ids(env):
    seed(env)
    a = fresh()
    b = fresh()
    login(a, "boss", "bosspassword")
    login(b, "tma", "tmapassword")

    doc_a, rev_a = get_state_and_rev(a)
    doc_b, rev_b = get_state_and_rev(b)

    # Both browsers independently compute the same "next" id, exactly as two
    # people adding a matter around the same moment would.
    doc_a["records"].append({"id": "t-003", "clientId": "c-1", "ipType": "trademark",
                             "brand": "FROM-A", "appno": "X", "status": "filed"})
    doc_b["records"].append({"id": "t-003", "clientId": "c-1", "ipType": "trademark",
                             "brand": "FROM-B", "appno": "Y", "status": "filed"})

    assert put_with_revision(a, doc_a, rev_a).status_code == 200
    r2 = put_with_revision(b, doc_b, rev_b)
    assert r2.status_code == 200

    final = a.get("/api/state").json()["state"]
    ids = [r["id"] for r in final["records"]]
    brands = [r["brand"] for r in final["records"]]
    assert len(ids) == len(set(ids)), "duplicate ids after concurrent adds: %s" % ids
    assert "FROM-A" in brands
    assert "FROM-B" in brands, "one of two concurrently added matters was lost"


def test_id_remap_is_reported_and_no_data_is_silently_lost(env):
    seed(env)
    a = fresh()
    b = fresh()
    login(a, "boss", "bosspassword")
    login(b, "tma", "tmapassword")

    doc_a, rev_a = get_state_and_rev(a)
    doc_b, rev_b = get_state_and_rev(b)
    doc_a["records"].append({"id": "t-003", "clientId": "c-1", "ipType": "trademark",
                             "brand": "FROM-A", "appno": "X", "status": "filed"})
    doc_b["records"].append({"id": "t-003", "clientId": "c-1", "ipType": "trademark",
                             "brand": "FROM-B", "appno": "Y", "status": "filed"})
    put_with_revision(a, doc_a, rev_a)
    resp = put_with_revision(b, doc_b, rev_b).json()
    assert "idRemap" in resp
    new_id = resp["idRemap"]["records"]["t-003"]
    assert new_id != "t-003"

    final = a.get("/api/state").json()["state"]
    remapped = [r for r in final["records"] if r["id"] == new_id]
    assert remapped and remapped[0]["brand"] == "FROM-B"


def test_concurrent_client_id_collision_reassigns_and_fixes_record_reference(env):
    seed(env)
    a = fresh()
    b = fresh()
    login(a, "boss", "bosspassword")
    login(b, "tma", "tmapassword")

    doc_a, rev_a = get_state_and_rev(a)
    doc_b, rev_b = get_state_and_rev(b)
    doc_a["clients"].append({"id": "c-2", "name": "From A Ltd"})
    doc_b["clients"].append({"id": "c-2", "name": "From B Ltd"})
    doc_b["records"].append({"id": "t-010", "clientId": "c-2", "ipType": "trademark",
                             "brand": "B's matter", "appno": "Z", "status": "filed"})

    put_with_revision(a, doc_a, rev_a)
    resp = put_with_revision(b, doc_b, rev_b).json()

    final = a.get("/api/state").json()["state"]
    names = sorted(c["name"] for c in final["clients"])
    assert names == ["Acme", "From A Ltd", "From B Ltd"]

    new_client_id = resp["idRemap"]["clients"]["c-2"]
    matter = [r for r in final["records"] if r["brand"] == "B's matter"][0]
    assert matter["clientId"] == new_client_id, \
        "record's clientId must follow its client's reassigned id"


# --- Resurrection: a save must not erase something it never saw -----------

def test_a_stale_save_does_not_delete_a_matter_it_never_saw(env):
    seed(env)
    a = fresh()
    login(a, "boss", "bosspassword")
    doc_a, rev_a = get_state_and_rev(a)   # A's baseline: only t-001, t-002

    b = fresh()
    login(b, "tma", "tmapassword")
    doc_b, rev_b = get_state_and_rev(b)
    doc_b["records"].append({"id": "t-999", "clientId": "c-1", "ipType": "trademark",
                             "brand": "NEW-BY-B", "appno": "Q", "status": "filed"})
    assert put_with_revision(b, doc_b, rev_b).status_code == 200

    # A now saves an unrelated edit, using ITS OLD baseline that never had
    # t-999 -- and A's payload naturally omits it, since A never knew it existed.
    doc_a["records"][0]["brand"] = "EDITED-BY-A"
    put_with_revision(a, doc_a, rev_a)

    final = a.get("/api/state").json()["state"]
    brands = {r["brand"] for r in final["records"]}
    assert "NEW-BY-B" in brands, "A's stale save destroyed a matter it never saw"
    assert "EDITED-BY-A" in brands


# --- Deletion still works, with and without a revision header --------------

def test_delete_still_works_with_revision_header(env):
    seed(env)
    login(env, "boss", "bosspassword")
    doc, rev = get_state_and_rev(env)
    doc["records"] = [r for r in doc["records"] if r["id"] != "t-001"]
    assert put_with_revision(env, doc, rev).status_code == 200
    ids = [r["id"] for r in env.get("/api/state").json()["state"]["records"]]
    assert "t-001" not in ids
    assert "t-002" in ids


def test_delete_still_works_without_revision_header(env):
    """The common case today: the frontend didn't send a revision at all."""
    seed(env)
    login(env, "boss", "bosspassword")
    doc = env.get("/api/state").json()["state"]
    doc["records"] = [r for r in doc["records"] if r["id"] != "t-001"]
    assert env.put("/api/state", json=doc).status_code == 200
    ids = [r["id"] for r in env.get("/api/state").json()["state"]["records"]]
    assert "t-001" not in ids


def test_clear_all_still_works_for_trademark_admin(env):
    """Bulk clear is a deliberate, in-scope action for a role with delete_matter."""
    seed(env)
    login(env, "tma", "tmapassword")
    doc, rev = get_state_and_rev(env)
    doc["records"] = []
    assert put_with_revision(env, doc, rev).status_code == 200
    assert env.get("/api/state").json()["state"]["records"] == []


# --- Assignment validation ---------------------------------------------------

def test_unknown_assignee_is_cleared_not_silently_stored(env):
    seed(env)
    login(env, "boss", "bosspassword")
    doc, rev = get_state_and_rev(env)
    doc["records"][0]["assignedTo"] = "nosuchperson"
    resp = put_with_revision(env, doc, rev).json()
    assert resp.get("clearedAssignments") == ["t-001"]

    got = env.get("/api/state").json()["state"]["records"][0]
    assert got["assignedTo"] == ""


def test_valid_assignee_is_kept(env):
    seed(env)
    login(env, "boss", "bosspassword")
    doc, rev = get_state_and_rev(env)
    doc["records"][0]["assignedTo"] = "tma"
    resp = put_with_revision(env, doc, rev).json()
    assert "clearedAssignments" not in resp
    assert env.get("/api/state").json()["state"]["records"][0]["assignedTo"] == "tma"


def test_assignee_check_is_case_insensitive(env):
    seed(env)
    login(env, "boss", "bosspassword")
    doc, rev = get_state_and_rev(env)
    doc["records"][0]["assignedTo"] = "TMA"
    resp = put_with_revision(env, doc, rev).json()
    assert "clearedAssignments" not in resp


def test_suspended_users_assignment_is_cleared(env):
    seed(env)
    login(env, "boss", "bosspassword")
    auth.set_active(auth.get_user_by_name("dee")["id"], False)
    doc, rev = get_state_and_rev(env)
    # t-001 was already assigned to dee before dee was suspended.
    resp = put_with_revision(env, doc, rev).json()
    assert resp.get("clearedAssignments") == ["t-001"]


# --- Bulk-manage capability separated from delete_matter ---------------------

def test_bulk_manage_is_superadmin_only():
    assert roles.can(roles.SUPERADMIN, "bulk_manage") is True
    assert roles.can(roles.TRADEMARK_ADMIN, "bulk_manage") is False
    assert roles.can(roles.DRAFTER, "bulk_manage") is False


def test_delete_matter_unaffected_by_bulk_manage_split():
    """Per-row delete must still work for trademark_admin."""
    assert roles.can(roles.TRADEMARK_ADMIN, "delete_matter") is True
