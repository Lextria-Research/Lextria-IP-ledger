"""Tests for authentication and role enforcement.

The point of these is adversarial: they check that a restricted role cannot get
at, or destroy, what it is not entitled to -- even when its client sends a
payload that tries to.
"""

import pathlib
import sys

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from backend import auth, db, roles  # noqa: E402


FINANCE = {
    "officialFee": "9000",
    "professionalFee": "15000",
    "amountPaid": "9000",
    "paymentStatus": "Partly paid",
    "invoiceRef": "INV-2026-014",
}

LEDGER = {
    "clients": [{"id": "c-1", "name": "Acme Ltd"}],
    "records": [
        dict({"id": "t-001", "clientId": "c-1", "ipType": "trademark",
              "brand": "ACMEBRAND", "appno": "TM-1", "status": "filed",
              "assignedTo": "dee"}, **FINANCE),
        dict({"id": "t-002", "clientId": "c-1", "ipType": "copyright",
              "brand": "Handbook", "appno": "CR-1", "status": "cr_filed",
              "assignedTo": "someone_else"}, **FINANCE),
    ],
    "log": [{"ts": "2026-01-01T00:00:00Z", "summary": "seeded"}],
    "nextClientSeq": 2, "nextRecordSeq": 3,
}


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "test.db")
    from backend.main import app
    with TestClient(app, base_url="http://localhost") as c:
        auth.create_user("boss", "bosspassword", roles.SUPERADMIN)
        auth.create_user("tma", "tmapassword", roles.TRADEMARK_ADMIN)
        auth.create_user("dee", "deepassword", roles.DRAFTER)
        yield c


def login(c, username, password):
    r = c.post("/api/login", json={"username": username, "password": password})
    assert r.status_code == 200, r.text
    return r


def seed(c):
    login(c, "boss", "bosspassword")
    assert c.put("/api/state", json=LEDGER).status_code == 200
    c.post("/api/logout")


# --- Authentication ---------------------------------------------------------

def test_state_requires_sign_in(client):
    d = client.get("/api/state").json()
    assert d["authorized"] is False and d["state"] is None


def test_write_requires_sign_in(client):
    assert client.put("/api/state", json=LEDGER).status_code == 401


def test_wrong_password_rejected(client):
    assert client.post("/api/login",
                       json={"username": "boss", "password": "nope"}).status_code == 401


def test_unknown_user_gives_same_error_as_wrong_password(client):
    a = client.post("/api/login", json={"username": "boss", "password": "nope"})
    b = client.post("/api/login", json={"username": "ghost", "password": "nope"})
    assert a.json()["error"] == b.json()["error"]


def test_logout_ends_session(client):
    login(client, "boss", "bosspassword")
    assert client.get("/api/me").json()["signedIn"] is True
    client.post("/api/logout")
    assert client.get("/api/me").json()["signedIn"] is False


def test_password_is_hashed_not_stored(client):
    user = auth.get_user_by_name("boss")
    assert "bosspassword" not in user["password_hash"]
    assert user["password_hash"].startswith("pbkdf2_sha256$")


def test_session_cookie_is_httponly(client):
    r = login(client, "boss", "bosspassword")
    assert "httponly" in r.headers["set-cookie"].lower()


# --- Superadmin -------------------------------------------------------------

def test_superadmin_sees_financials(client):
    seed(client)
    login(client, "boss", "bosspassword")
    rec = client.get("/api/state").json()["state"]["records"][0]
    assert rec["professionalFee"] == "15000"


def test_superadmin_sees_all_records(client):
    seed(client)
    login(client, "boss", "bosspassword")
    assert len(client.get("/api/state").json()["state"]["records"]) == 2


# --- Trademark admin: everything except financials --------------------------

def test_trademark_admin_sees_all_records(client):
    seed(client)
    login(client, "tma", "tmapassword")
    assert len(client.get("/api/state").json()["state"]["records"]) == 2


def test_trademark_admin_never_receives_financial_fields(client):
    seed(client)
    login(client, "tma", "tmapassword")
    body = client.get("/api/state").text
    for field in roles.FINANCIAL_FIELDS:
        assert field not in body, f"{field} leaked to trademark admin"
    for value in FINANCE.values():
        assert value not in body, f"value {value} leaked to trademark admin"


def test_trademark_admin_save_does_not_blank_financials(client):
    """The payload it sends has no financial fields; storage must keep them."""
    seed(client)
    login(client, "tma", "tmapassword")
    doc = client.get("/api/state").json()["state"]
    doc["records"][0]["brand"] = "RENAMED"
    assert client.put("/api/state", json=doc).status_code == 200

    client.post("/api/logout")
    login(client, "boss", "bosspassword")
    rec = client.get("/api/state").json()["state"]["records"][0]
    assert rec["brand"] == "RENAMED"           # its edit applied
    assert rec["professionalFee"] == "15000"   # financials survived


def test_trademark_admin_cannot_inject_financials(client):
    seed(client)
    login(client, "tma", "tmapassword")
    doc = client.get("/api/state").json()["state"]
    doc["records"][0]["professionalFee"] = "1"
    client.put("/api/state", json=doc)

    client.post("/api/logout")
    login(client, "boss", "bosspassword")
    assert client.get("/api/state").json()["state"]["records"][0]["professionalFee"] == "15000"


def test_trademark_admin_can_add_a_matter(client):
    seed(client)
    login(client, "tma", "tmapassword")
    doc = client.get("/api/state").json()["state"]
    doc["records"].append({"id": "t-003", "clientId": "c-1", "ipType": "design",
                           "brand": "New Design", "appno": "DS-1", "status": "id_filed"})
    assert client.put("/api/state", json=doc).status_code == 200
    assert len(client.get("/api/state").json()["state"]["records"]) == 3


def test_trademark_admin_cannot_manage_users(client):
    seed(client)
    login(client, "tma", "tmapassword")
    assert client.get("/api/users").status_code == 403
    assert client.post("/api/users", json={"username": "x", "password": "12345678",
                                           "role": "drafter"}).status_code == 403


# --- Drafter: assigned matters only, no financials, status/deadlines only ---

def test_drafter_sees_only_assigned_matters(client):
    seed(client)
    login(client, "dee", "deepassword")
    recs = client.get("/api/state").json()["state"]["records"]
    assert [r["id"] for r in recs] == ["t-001"]


def test_drafter_never_receives_financial_fields(client):
    seed(client)
    login(client, "dee", "deepassword")
    body = client.get("/api/state").text
    for value in FINANCE.values():
        assert value not in body


def test_drafter_does_not_see_other_matters_via_the_log(client):
    seed(client)
    login(client, "dee", "deepassword")
    assert client.get("/api/state").json()["state"]["log"] == []


def test_drafter_does_not_see_the_whole_client_roster(client):
    """Who a firm acts for is confidential in itself.

    Filtering the records but shipping every client still discloses the roster
    through the client dropdown.
    """
    login(client, "boss", "bosspassword")
    doc = dict(LEDGER)
    doc["clients"] = [{"id": "c-1", "name": "Acme Ltd"},
                      {"id": "c-9", "name": "Confidential Client Ltd"}]
    client.put("/api/state", json=doc)
    client.post("/api/logout")

    login(client, "dee", "deepassword")
    body = client.get("/api/state").text
    assert "Confidential Client Ltd" not in body
    names = [c["name"] for c in client.get("/api/state").json()["state"]["clients"]]
    assert names == ["Acme Ltd"]


def test_drafter_save_cannot_delete_unseen_matters(client):
    """The regression that makes server-side merge necessary at all."""
    seed(client)
    login(client, "dee", "deepassword")
    doc = client.get("/api/state").json()["state"]
    assert len(doc["records"]) == 1          # it only ever saw one
    doc["records"][0]["status"] = "registered"
    assert client.put("/api/state", json=doc).status_code == 200

    client.post("/api/logout")
    login(client, "boss", "bosspassword")
    full = client.get("/api/state").json()["state"]
    assert len(full["records"]) == 2, "drafter's save wiped a matter it could not see"
    assert full["records"][0]["status"] == "registered"


def test_drafter_can_change_status_and_deadline(client):
    seed(client)
    login(client, "dee", "deepassword")
    doc = client.get("/api/state").json()["state"]
    doc["records"][0]["status"] = "objected"
    doc["records"][0]["actionDate"] = "2026-12-01"
    client.put("/api/state", json=doc)

    client.post("/api/logout")
    login(client, "boss", "bosspassword")
    rec = client.get("/api/state").json()["state"]["records"][0]
    assert rec["status"] == "objected"
    assert rec["actionDate"] == "2026-12-01"


def test_drafter_cannot_edit_matter_details(client):
    seed(client)
    login(client, "dee", "deepassword")
    doc = client.get("/api/state").json()["state"]
    doc["records"][0]["brand"] = "HIJACKED"
    client.put("/api/state", json=doc)

    client.post("/api/logout")
    login(client, "boss", "bosspassword")
    assert client.get("/api/state").json()["state"]["records"][0]["brand"] == "ACMEBRAND"


def test_drafter_cannot_add_a_matter(client):
    seed(client)
    login(client, "dee", "deepassword")
    doc = client.get("/api/state").json()["state"]
    doc["records"].append({"id": "t-999", "brand": "SNUCK IN", "ipType": "trademark"})
    client.put("/api/state", json=doc)

    client.post("/api/logout")
    login(client, "boss", "bosspassword")
    ids = [r["id"] for r in client.get("/api/state").json()["state"]["records"]]
    assert "t-999" not in ids


def test_drafter_cannot_reassign_a_matter_to_themselves(client):
    seed(client)
    login(client, "dee", "deepassword")
    doc = client.get("/api/state").json()["state"]
    # Forge a payload containing someone else's matter, reassigned.
    doc["records"].append({"id": "t-002", "assignedTo": "dee", "status": "cr_registered"})
    client.put("/api/state", json=doc)

    client.post("/api/logout")
    login(client, "boss", "bosspassword")
    other = [r for r in client.get("/api/state").json()["state"]["records"]
             if r["id"] == "t-002"][0]
    assert other["assignedTo"] == "someone_else"
    assert other["status"] == "cr_filed"


def test_drafter_cannot_edit_clients(client):
    seed(client)
    login(client, "dee", "deepassword")
    doc = client.get("/api/state").json()["state"]
    doc["clients"] = [{"id": "c-1", "name": "RENAMED"}]
    client.put("/api/state", json=doc)

    client.post("/api/logout")
    login(client, "boss", "bosspassword")
    assert client.get("/api/state").json()["state"]["clients"][0]["name"] == "Acme Ltd"


def test_drafter_cannot_manage_users(client):
    seed(client)
    login(client, "dee", "deepassword")
    assert client.get("/api/users").status_code == 403


# --- Capability table -------------------------------------------------------

@pytest.mark.parametrize("role,capability,expected", [
    (roles.SUPERADMIN, "view_financials", True),
    (roles.SUPERADMIN, "manage_users", True),
    (roles.TRADEMARK_ADMIN, "view_financials", False),
    (roles.TRADEMARK_ADMIN, "edit_matter", True),
    (roles.TRADEMARK_ADMIN, "export", True),
    (roles.TRADEMARK_ADMIN, "manage_users", False),
    (roles.DRAFTER, "view_financials", False),
    (roles.DRAFTER, "change_status", True),
    (roles.DRAFTER, "create_matter", False),
    (roles.DRAFTER, "edit_matter", False),
    (roles.DRAFTER, "export", False),
    (roles.DRAFTER, "delete_matter", False),
])
def test_capabilities(role, capability, expected):
    assert roles.can(role, capability) is expected


# --- Superadmin bootstrap ---------------------------------------------------

def test_superadmin_generated_once(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "boot.db")
    db.init_db()
    auth.init_auth_schema()
    first = auth.ensure_superadmin()
    assert first and len(first) >= 12
    assert auth.ensure_superadmin() is None      # not regenerated
    assert auth.authenticate("superadmin", first) is not None
