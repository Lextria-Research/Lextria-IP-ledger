"""Playwright walkthrough: sign in as each role and show what it can see.

Starts its own server on a spare port with a throwaway database, so it never
touches the ledger you are actually using. Drives the real UI and writes
numbered screenshots to tests/screenshots/.

    py tests/demo_roles.py            headless (default)
    py tests/demo_roles.py --headed   watch it happen in a real window
"""

import json
import shutil
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import requests
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))          # must precede the tests.* import below

from tests.uitext import contains      # noqa: E402

SHOTS = ROOT / "tests" / "screenshots"

SUPER_PW = "superadmin-demo-pw"
TMA_PW = "tmadmin-demo-pw"
DRAFTER_PW = "drafter-demo-pw"

# Two matters. Both carry fees; only the first is assigned to the drafter.
LEDGER = {
    "clients": [{"id": "c-1", "name": "Acme Innovations Ltd"},
                {"id": "c-2", "name": "Borealis Foods"}],
    "records": [
        {"id": "t-001", "clientId": "c-1", "ipType": "trademark",
         "brand": "ACMEBRAND", "cls": "42", "appno": "TM-99001",
         "markType": "Word", "status": "objected", "desc": "Software services",
         "action": "File response to Examination Report", "actionDate": "2026-10-15",
         "assignedTo": "priya",
         "officialFee": "9000", "professionalFee": "15000", "amountPaid": "9000",
         "paymentStatus": "Partly paid", "invoiceRef": "INV-2026-014",
         "applicants": [], "authors": [], "contributors": [], "timeline": []},
        {"id": "t-002", "clientId": "c-2", "ipType": "trademark",
         "brand": "BOREALIS", "cls": "29", "appno": "TM-99002",
         "markType": "Word + Logo", "status": "registered", "desc": "Frozen foods",
         "action": "File renewal before expiry", "renewDate": "2036-02-01",
         "assignedTo": "someone-else",
         "officialFee": "9000", "professionalFee": "42500", "amountPaid": "42500",
         "paymentStatus": "Paid", "invoiceRef": "INV-2026-021",
         "applicants": [], "authors": [], "contributors": [], "timeline": []},
    ],
    "log": [], "nextClientSeq": 3, "nextRecordSeq": 3,
}

step = 0


def say(msg):
    print(msg, flush=True)


def shot(page, name):
    global step
    step += 1
    path = SHOTS / ("%02d-%s.png" % (step, name))
    page.screenshot(path=str(path), full_page=False)
    say("        saved %s" % path.name)


def free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def sign_in(page, base, username, password):
    page.goto(base + "/")
    page.wait_for_selector("#signin-user", timeout=15000)
    page.fill("#signin-user", username)
    page.fill("#signin-pass", password)
    page.click('[data-action="signin-submit"]')
    page.wait_for_selector(".role-badge", timeout=15000)
    page.wait_for_timeout(700)


def visible_text(page):
    return page.inner_text("body")


def has(page, needle):
    """Is `needle` on screen, ignoring CSS casing and line wrapping?

    See tests/uitext.py -- the stylesheet upper-cases headers and labels, and
    narrow table cells wrap mid-phrase, so a raw substring test fails on
    styling rather than substance.
    """
    return contains(visible_text(page), needle)


def main():
    headed = "--headed" in sys.argv
    port = free_port()
    base = "http://127.0.0.1:%d" % port

    SHOTS.mkdir(parents=True, exist_ok=True)
    for old in SHOTS.glob("*.png"):
        old.unlink()

    # A throwaway database, so the ledger you are using is untouched.
    tmpdir = Path(tempfile.mkdtemp(prefix="lex_demo_"))
    env_db = tmpdir / "demo.db"
    launcher = tmpdir / "demo_app.py"
    launcher.write_text(
        "import pathlib, sys\n"
        "sys.path.insert(0, r'%s')\n"
        "from backend import db\n"
        "db.DB_PATH = pathlib.Path(r'%s')\n"
        "from backend.main import app\n" % (ROOT, env_db),
        encoding="utf-8",
    )

    say("\nStarting a demo server on %s (throwaway database)\n" % base)
    server = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "demo_app:app", "--port", str(port)],
        cwd=str(tmpdir), stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
    )
    try:
        for _ in range(60):
            try:
                if requests.get(base + "/api/health", timeout=1).status_code == 200:
                    break
            except Exception:
                pass
            time.sleep(0.5)
        else:
            raise RuntimeError("server did not start")

        # Set up accounts and data over the API, so the walkthrough itself can
        # concentrate on what each role sees.
        s = requests.Session()
        from backend import db as _db
        _db.DB_PATH = env_db          # must precede any auth call
        from backend import auth
        auth.set_password("superadmin", SUPER_PW)
        s.post(base + "/api/login",
               json={"username": "superadmin", "password": SUPER_PW}).raise_for_status()
        s.post(base + "/api/users",
               json={"username": "rakesh", "password": TMA_PW, "role": "trademark_admin"})
        s.post(base + "/api/users",
               json={"username": "priya", "password": DRAFTER_PW, "role": "drafter"})
        s.put(base + "/api/state", json=LEDGER).raise_for_status()
        say("Seeded 3 accounts and 2 matters (both with fees; ACMEBRAND assigned to priya).\n")

        with sync_playwright() as p:
            browser = p.chromium.launch(headless=not headed, slow_mo=400 if headed else 0)
            findings = []

            def note(ok, text):
                findings.append((ok, text))
                say("        %s %s" % ("OK  " if ok else "FAIL", text))

            # ---------------------------------------------------------------
            say("=" * 70)
            say(" 1. NOT SIGNED IN")
            say("=" * 70)
            ctx = browser.new_context(viewport={"width": 1400, "height": 900})
            page = ctx.new_page()
            page.goto(base + "/")
            page.wait_for_selector("#signin-user", timeout=15000)
            say("      The dashboard is behind a sign-in screen.")
            note(page.is_visible("#signin-user"), "sign-in form shown")
            note(not has(page, "ACMEBRAND"), "no ledger data on screen")
            shot(page, "signed-out")
            ctx.close()

            # ---------------------------------------------------------------
            say("\n" + "=" * 70)
            say(" 2. SUPERADMIN  -- sees everything, including money")
            say("=" * 70)
            ctx = browser.new_context(viewport={"width": 1400, "height": 900})
            page = ctx.new_page()
            sign_in(page, base, "superadmin", SUPER_PW)
            say("      Signed in. Badge: %r" % page.inner_text(".role-badge"))
            body = visible_text(page)
            note(contains(body, "ACMEBRAND") and contains(body, "BOREALIS"), "sees both matters")
            note(page.is_visible('[data-action="open-add"]'), "can add matters")
            note(page.is_visible('[data-action="open-export"]'), "can export")
            shot(page, "superadmin-ledger")

            say("      Opening a matter to show the financial fields...")
            page.click('[data-action="open-edit"]')
            page.wait_for_timeout(900)
            modal = page.inner_text(".modal") if page.is_visible(".modal") else ""
            note(contains(modal, "Financials"), "financial section present")
            note(page.is_visible('[data-field="professionalFee"]'), "professional fee field present")
            note(page.input_value('[data-field="professionalFee"]') == "15000",
                 "professional fee reads 15000")
            note(page.is_visible('[data-field="assignedTo"]'), "can set who a matter is assigned to")
            shot(page, "superadmin-financials")
            page.click('[data-action="close-modal"]')
            page.wait_for_timeout(400)

            say("      Settings -> People and access (superadmin only)...")
            page.click('[data-action="set-mode"][data-mode="settings"]')
            page.wait_for_timeout(1200)
            settings = visible_text(page)
            note(contains(settings, "People and access"), "user management card visible")
            note(contains(settings, "rakesh") and contains(settings, "priya"), "lists the other accounts")
            shot(page, "superadmin-users")
            ctx.close()

            # ---------------------------------------------------------------
            say("\n" + "=" * 70)
            say(" 3. TRADEMARK ADMIN (rakesh) -- every matter, no money")
            say("=" * 70)
            ctx = browser.new_context(viewport={"width": 1400, "height": 900})
            page = ctx.new_page()
            sign_in(page, base, "rakesh", TMA_PW)
            say("      Signed in. Badge: %r" % page.inner_text(".role-badge"))
            body = visible_text(page)
            note("ACMEBRAND" in body and "BOREALIS" in body, "sees BOTH matters")
            note(page.is_visible('[data-action="open-add"]'), "can still add matters")
            shot(page, "tmadmin-ledger")

            # The real check is the payload, not the pixels.
            payload = page.evaluate(
                "async () => (await (await fetch('/api/state', "
                "{credentials:'same-origin'})).text())")
            note("15000" not in payload and "42500" not in payload,
                 "no fee VALUE anywhere in the server response")
            note("professionalFee" not in payload,
                 "no financial FIELD in the server response")
            say("      (checked the raw API response, not just the rendered page)")

            page.click('[data-action="open-edit"]')
            page.wait_for_timeout(900)
            note(not page.is_visible('[data-field="professionalFee"]'),
                 "financial fields absent from the edit form")
            shot(page, "tmadmin-no-financials")
            page.click('[data-action="close-modal"]')
            page.wait_for_timeout(300)

            page.click('[data-action="set-mode"][data-mode="settings"]')
            page.wait_for_timeout(900)
            note(not has(page, "People and access"), "no user management")
            shot(page, "tmadmin-settings")
            ctx.close()

            # ---------------------------------------------------------------
            say("\n" + "=" * 70)
            say(" 4. DRAFTER (priya) -- only her own matters")
            say("=" * 70)
            ctx = browser.new_context(viewport={"width": 1400, "height": 900})
            page = ctx.new_page()
            sign_in(page, base, "priya", DRAFTER_PW)
            say("      Signed in. Badge: %r" % page.inner_text(".role-badge"))
            body = visible_text(page)
            note(contains(body, "ACMEBRAND"), "sees the matter assigned to her")
            note(contains(body, "Acme Innovations Ltd"),
                 "her own client shown in full (name wraps in the cell)")
            note(not contains(body, "BOREALIS"), "does NOT see the unassigned matter")
            note(not contains(body, "Borealis Foods"), "does not even see that client")
            note(not page.is_visible('[data-action="open-add"]'), "no 'Add matter' button")
            note(not page.is_visible('[data-action="open-export"]'), "no 'Export' button")
            shot(page, "drafter-ledger")

            payload = page.evaluate(
                "async () => (await (await fetch('/api/state', "
                "{credentials:'same-origin'})).text())")
            note("BOREALIS" not in payload,
                 "the other matter is not in the server response at all")
            note("15000" not in payload, "no fee values in the server response")

            say("      Advancing the status -- the one thing she may change...")
            page.select_option('[data-action="change-status"]', "hearing_fixed")
            page.wait_for_timeout(1500)
            note(has(page, "Hearing Fixed"), "status change applied")
            shot(page, "drafter-status-change")
            ctx.close()

            # ---------------------------------------------------------------
            say("\n" + "=" * 70)
            say(" 5. DID HER SAVE DESTROY THE MATTER SHE COULD NOT SEE?")
            say("=" * 70)
            say("      Her browser held a 1-matter ledger and PUT it back.")
            say("      Signing in as superadmin to check the real ledger...")
            ctx = browser.new_context(viewport={"width": 1400, "height": 900})
            page = ctx.new_page()
            sign_in(page, base, "superadmin", SUPER_PW)
            body = visible_text(page)
            note(contains(body, "BOREALIS"), "BOREALIS survived the drafter's save")
            note(contains(body, "ACMEBRAND"), "ACMEBRAND still there")
            note(contains(body, "Hearing Fixed"), "her status change WAS applied")

            page.click('[data-action="open-edit"]')
            page.wait_for_timeout(900)
            note(page.input_value('[data-field="professionalFee"]') == "15000",
                 "the fee she never saw is intact")
            shot(page, "superadmin-after-drafter-save")
            ctx.close()

            browser.close()

        say("\n" + "=" * 70)
        passed = sum(1 for ok, _ in findings if ok)
        failed = [t for ok, t in findings if not ok]
        say("  %d/%d checks passed" % (passed, len(findings)))
        if failed:
            say("  FAILED: " + "; ".join(failed))
        say("  screenshots in %s" % SHOTS)
        say("=" * 70 + "\n")
        return 1 if failed else 0
    finally:
        server.terminate()
        try:
            server.wait(timeout=10)
        except Exception:
            server.kill()
        shutil.rmtree(tmpdir, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
