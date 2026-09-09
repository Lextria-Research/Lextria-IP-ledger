"""Regression tests for the request-level hardening in backend/security.py.

Each test here corresponds to a hole that was confirmed open by probing a
running server, so these exist to stop them reopening.
"""

import pathlib
import sys
import tempfile

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from backend import auth, db, roles, security  # noqa: E402

db.DB_PATH = pathlib.Path(tempfile.mkdtemp()) / "test.db"

from backend.main import app  # noqa: E402


@pytest.fixture
def client():
    # base_url matters: TestClient defaults to Host "testserver", a domain name,
    # which host_is_safe correctly rejects. Real clients use localhost or an IP.
    with TestClient(app, base_url="http://localhost") as c:
        # Signed in so that a 401 never masks the hardening behaviour under test.
        auth.create_user("tester", "testerpassword", roles.SUPERADMIN)
        c.post("/api/login", json={"username": "tester", "password": "testerpassword"})
        yield c


# --- Host validation / DNS rebinding ---------------------------------------

@pytest.mark.parametrize("host", [
    "localhost", "localhost:8000", "LOCALHOST:8000", "localhost.",
    "127.0.0.1", "127.0.0.1:8000", "192.168.1.20:8000", "10.0.0.5",
    "[::1]", "[::1]:8000", "::1",
])
def test_legitimate_hosts_are_served(host):
    assert security.host_is_safe(host) is True


@pytest.mark.parametrize("host", [
    "evil.example.com", "evil.example.com:8000",
    "localhost.evil.com", "127.0.0.1.evil.com", "attacker.io", "",
])
def test_domain_names_are_rejected(host):
    """A registered domain in Host is the tell of a DNS-rebinding attempt."""
    assert security.host_is_safe(host) is False


def test_rebinding_request_gets_421(client):
    r = client.get("/api/state", headers={"Host": "evil.example.com"})
    assert r.status_code == 421


def test_rebinding_cannot_write(client):
    r = client.put("/api/state", json={"clients": []}, headers={"Host": "evil.example.com"})
    assert r.status_code == 421


# --- Body size cap ----------------------------------------------------------

def test_oversized_body_rejected(client):
    payload = {"clients": [], "records": [], "log": [],
               "pad": "A" * (security.MAX_BODY_BYTES + 1024)}
    assert client.put("/api/state", json=payload).status_code == 413


def test_oversized_body_does_not_corrupt_stored_ledger(client):
    good = {"clients": [{"id": "c-1", "name": "Acme"}], "records": [], "log": []}
    assert client.put("/api/state", json=good).status_code == 200
    client.put("/api/state", json={"pad": "A" * (security.MAX_BODY_BYTES + 1024)})
    got = client.get("/api/state").json()["state"]
    # The merge guarantees nextClientSeq/nextRecordSeq are present (backend/
    # roles.py), even though `good` did not set them -- compare what this test
    # is actually about: that the oversized PUT changed nothing.
    assert got["clients"] == good["clients"]
    assert got["records"] == good["records"]
    assert got["log"] == good["log"]


def test_normal_sized_ledger_still_accepted(client):
    assert client.put("/api/state", json={"clients": [], "records": [], "log": []}).status_code == 200


# --- Interactive docs -------------------------------------------------------

@pytest.mark.parametrize("path", ["/api/docs", "/api/redoc", "/api/openapi.json", "/docs", "/openapi.json"])
def test_no_interactive_docs(client, path):
    """Swagger UI on an unauthenticated API is a one-click ledger wipe."""
    assert client.get(path).status_code == 404


# --- Response headers -------------------------------------------------------

@pytest.mark.parametrize("header,expected", [
    ("X-Content-Type-Options", "nosniff"),
    ("X-Frame-Options", "DENY"),
    ("Referrer-Policy", "no-referrer"),
    ("Cache-Control", "no-store"),
])
def test_security_headers_present(client, header, expected):
    assert client.get("/").headers.get(header) == expected


def test_csp_forbids_inline_script(client):
    """The page loads its JS from a file, so script-src needs no escape hatch."""
    csp = client.get("/").headers.get("Content-Security-Policy", "")
    assert "script-src 'self'" in csp
    assert "unsafe-inline" not in csp.split("style-src")[0]
    assert "frame-ancestors 'none'" in csp


# --- Static file exposure ---------------------------------------------------

@pytest.mark.parametrize("path", [
    "/backend/main.py", "/backend/db.py", "/backend/security.py",
    "/backend/lextria.db", "/.git/config", "/README.md", "/.gitignore",
    "/static/../backend/db.py",
])
def test_only_static_dir_is_reachable(client, path):
    assert client.get(path).status_code in (404, 403)


@pytest.mark.parametrize("path", [
    "/static/css/app.css", "/static/js/app.js", "/static/img/lextria-logo.png",
])
def test_frontend_assets_are_reachable(client, path):
    assert client.get(path).status_code == 200
