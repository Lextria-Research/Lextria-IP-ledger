"""Functional tests for the ledger API and its SQLite persistence."""

import pathlib
import sqlite3
import sys
import tempfile

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from backend import auth, db, roles  # noqa: E402


@pytest.fixture
def client(tmp_path, monkeypatch):
    # A fresh database per test, so ordering never matters.
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "test.db")
    from backend.main import app
    # Host must be localhost or an IP — see backend/security.host_is_safe.
    with TestClient(app, base_url="http://localhost") as c:
        # Every ledger endpoint now requires a session; these tests cover the
        # API's behaviour, not its access control (see test_roles.py for that),
        # so they run as a superadmin.
        auth.create_user("tester", "testerpassword", roles.SUPERADMIN)
        c.post("/api/login", json={"username": "tester", "password": "testerpassword"})
        yield c


LEDGER = {
    "clients": [{"id": "c-1", "name": "Acme Ltd"}],
    "records": [
        {"id": "t-001", "clientId": "c-1", "ipType": "trademark", "brand": "ACME", "status": "filed"},
        {"id": "t-002", "clientId": "c-1", "ipType": "copyright", "brand": "Handbook", "status": "cr_filed"},
        {"id": "t-003", "clientId": "c-1", "ipType": "design", "brand": "Bottle", "status": "id_filed"},
    ],
    "nextClientSeq": 2, "nextRecordSeq": 4, "log": [],
}


def test_health(client):
    assert client.get("/api/health").json() == {"status": "ok"}


def test_fresh_database_reports_no_state(client):
    """state must be null, not {} — the SPA seeds itself only when it is null."""
    d = client.get("/api/state").json()
    assert d["configured"] is True
    assert d["authorized"] is True
    assert d["state"] is None


def test_signed_in_response_names_the_user_and_role(client):
    d = client.get("/api/state").json()
    assert d["authRequired"] is True          # accounts exist, so the SPA gates
    assert d["user"]["username"] == "tester"
    assert d["user"]["role"] == roles.SUPERADMIN
    assert "view_financials" in d["user"]["can"]


def test_round_trip_is_byte_identical(client):
    assert client.put("/api/state", json=LEDGER).json() == {"ok": True, "revision": 1}
    assert client.get("/api/state").json()["state"] == LEDGER


def test_all_three_ip_types_survive(client):
    client.put("/api/state", json=LEDGER)
    got = client.get("/api/state").json()["state"]
    assert sorted(r["ipType"] for r in got["records"]) == ["copyright", "design", "trademark"]


def test_revision_increments_and_history_archives(client):
    client.put("/api/state", json=LEDGER)
    second = dict(LEDGER, log=[{"ts": "x", "summary": "y"}])
    assert client.put("/api/state", json=second).json()["revision"] == 2

    conn = sqlite3.connect(db.DB_PATH)
    assert conn.execute("SELECT revision FROM ledger_history").fetchall() == [(1,)]
    assert conn.execute("SELECT COUNT(*) FROM ledger_state").fetchone() == (1,)
    conn.close()


@pytest.mark.parametrize("body", [[1, 2], "a string", 42])
def test_non_object_bodies_rejected(client, body):
    assert client.put("/api/state", json=body).status_code == 400


def test_malformed_json_rejected(client):
    r = client.put("/api/state", content=b"{nope",
                   headers={"Content-Type": "application/json"})
    assert r.status_code == 400


def test_bad_put_does_not_corrupt_stored_ledger(client):
    client.put("/api/state", json=LEDGER)
    client.put("/api/state", json=[1, 2])
    client.put("/api/state", content=b"{nope", headers={"Content-Type": "application/json"})
    assert client.get("/api/state").json()["state"] == LEDGER


def test_unicode_round_trip(client):
    """Client names and titles of work are not ASCII-only."""
    uni = {"clients": [{"id": "c-1", "name": "Ünïcode — 商標 ✓"}], "records": [], "log": []}
    client.put("/api/state", json=uni)
    got = client.get("/api/state").json()["state"]
    # The merge always guarantees nextClientSeq/nextRecordSeq are present and
    # monotonic (backend/roles.py), even when the payload omitted them -- so
    # compare the fields this test actually cares about, not the whole document.
    assert got["clients"] == uni["clients"]
    assert got["records"] == uni["records"]
    assert got["log"] == uni["log"]


@pytest.mark.parametrize("method", ["post", "delete", "patch"])
def test_unsupported_methods(client, method):
    assert getattr(client, method)("/api/state").status_code == 405


def test_index_is_served(client):
    r = client.get("/")
    assert r.status_code == 200
    assert "app-state" in r.text
