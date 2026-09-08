"""End-to-end test: real browser, real UI clicks, real FastAPI backend, real SQLite.

Starts the server, drives the actual dashboard in headless Edge over the Chrome
DevTools Protocol -- adding a client and one matter of each IP type through the
UI, not the API -- reloads to prove persistence, then reads the SQLite file
directly to confirm what the browser did actually landed on disk.

Run:  py tests/e2e_browser.py
"""

import asyncio
import json
import shutil
import socket
import sqlite3
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import requests
import websockets

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))          # must precede the tests.* import below

from tests.uitext import BROWSER_HELPER  # noqa: E402
EDGE = r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"

results = []


def check(name, ok, detail=""):
    results.append((name, bool(ok)))
    mark = "PASS" if ok else "FAIL"
    print("  [%s] %s" % (mark, name), flush=True)
    if not ok and detail != "":
        print("         -> %s" % (detail,), flush=True)


def free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class CDP:
    """Minimal Chrome DevTools Protocol client."""

    def __init__(self, ws):
        self.ws = ws
        self.n = 0

    async def send(self, method, **params):
        self.n += 1
        msg_id = self.n
        await self.ws.send(json.dumps({"id": msg_id, "method": method, "params": params}))
        while True:
            raw = json.loads(await self.ws.recv())
            if raw.get("id") == msg_id:
                if "error" in raw:
                    raise RuntimeError("%s: %s" % (method, raw["error"]))
                return raw.get("result", {})

    async def js(self, expression):
        """Evaluate an expression in the page and return its value."""
        r = await self.send(
            "Runtime.evaluate",
            expression=expression,
            returnByValue=True,
            awaitPromise=True,
        )
        if r.get("exceptionDetails"):
            desc = r["exceptionDetails"].get("exception", {}).get("description", "?")
            raise RuntimeError("JS error: %s" % (desc,))
        return r["result"].get("value")


# Injected once per page load. Sets fields the way a user does, firing the same
# events the app's own listeners are bound to ('input' for text, 'change' for
# selects) rather than poking app state directly.
HELPERS = """
window.__set = function (name, value) {
  var el = document.querySelector('[data-field="' + name + '"]');
  if (!el) { return 'missing field: ' + name; }
  el.value = value;
  el.dispatchEvent(new Event(el.tagName === 'SELECT' ? 'change' : 'input', { bubbles: true }));
  return 'ok';
};
window.__click = function (action) {
  var el = document.querySelector('[data-action="' + action + '"]');
  if (!el) { return 'missing action: ' + action; }
  el.click();
  return 'ok';
};
window.__tab = function (t) {
  var el = document.querySelector('[data-iptype="' + t + '"]');
  if (!el) { return 'missing tab: ' + t; }
  el.click();
  return 'ok';
};
""" + BROWSER_HELPER + """
window.__errors = [];
window.addEventListener('error', function (e) { window.__errors.push(String(e.message)); });
'injected';
"""


async def add_matter(cdp, ip_type, brand, appno, client_choice, new_client_name=None):
    """Add one matter through the UI, as a user would."""
    await cdp.js("window.__tab(%s)" % json.dumps(ip_type))
    await asyncio.sleep(0.4)
    await cdp.js("window.__click('open-add')")
    await asyncio.sleep(0.5)
    await cdp.js("window.__set('clientId', %s)" % json.dumps(client_choice))
    await asyncio.sleep(0.4)
    if new_client_name:
        await cdp.js("window.__set('newClientName', %s)" % json.dumps(new_client_name))
    await cdp.js("window.__set('brand', %s)" % json.dumps(brand))
    await cdp.js("window.__set('appno', %s)" % json.dumps(appno))
    await asyncio.sleep(0.3)
    await cdp.js("window.__click('save-record')")
    await asyncio.sleep(1.0)  # optimistic render + PUT to the backend


ADMIN_PW = "e2e-superadmin-pw"


async def run():
    port = free_port()
    dbg = free_port()

    # A throwaway database in a temp directory. This test used to point at the
    # real backend/lextria.db and delete it on startup, which destroyed whatever
    # ledger was there and failed outright whenever a live server held the file.
    tmpdir = Path(tempfile.mkdtemp(prefix="lex_e2e_db_"))
    db_file = tmpdir / "e2e.db"
    (tmpdir / "e2e_app.py").write_text(
        "import pathlib, sys\n"
        "sys.path.insert(0, r'%s')\n"
        "from backend import db\n"
        "db.DB_PATH = pathlib.Path(r'%s')\n"
        "from backend.main import app\n" % (ROOT, db_file),
        encoding="utf-8",
    )

    base = "http://127.0.0.1:%d" % port
    print("\nStarting backend on %s (throwaway database) ..." % base, flush=True)
    server = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "e2e_app:app", "--port", str(port)],
        cwd=str(tmpdir), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    profile = tempfile.mkdtemp(prefix="lex_e2e_")
    browser = None
    try:
        for _ in range(60):
            try:
                if requests.get(base + "/api/health", timeout=1).status_code == 200:
                    break
            except Exception:
                pass
            time.sleep(0.5)
        else:
            raise RuntimeError("backend did not start")
        print("Backend up.", flush=True)
        # The server generates a random superadmin password on first run; give
        # it one this test knows, so the UI sign-in below can succeed.
        from backend import db as _db
        _db.DB_PATH = db_file
        from backend import auth as _auth
        _auth.set_password("superadmin", ADMIN_PW)

        print("Launching headless Edge (CDP on :%d) ..." % dbg, flush=True)
        browser = subprocess.Popen(
            [EDGE, "--headless=new", "--disable-gpu",
             "--remote-debugging-port=%d" % dbg,
             "--user-data-dir=%s" % profile,
             "--no-first-run", "--no-default-browser-check", "about:blank"],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        pages = []
        for _ in range(60):
            try:
                targets = requests.get("http://127.0.0.1:%d/json" % dbg, timeout=1).json()
                pages = [t for t in targets if t.get("type") == "page"]
                if pages:
                    break
            except Exception:
                pass
            time.sleep(0.5)
        if not pages:
            raise RuntimeError("browser did not expose a CDP page target")
        print("Browser up.\n", flush=True)

        async with websockets.connect(pages[0]["webSocketDebuggerUrl"], max_size=None) as ws:
            cdp = CDP(ws)
            await cdp.send("Runtime.enable")
            await cdp.send("Page.enable")

            print("--- 1. Page loads, then sign in ---", flush=True)
            await cdp.send("Page.navigate", url=base + "/")
            await asyncio.sleep(3.0)
            await cdp.js(HELPERS)

            check("sign-in screen shown before any ledger data",
                  await cdp.js("!!document.getElementById('signin-user')"))
            await cdp.js(
                "(function(){"
                "var u=document.getElementById('signin-user');"
                "var p=document.getElementById('signin-pass');"
                "u.value=" + json.dumps("superadmin") + ";"
                "u.dispatchEvent(new Event('input',{bubbles:true}));"
                "p.value=" + json.dumps(ADMIN_PW) + ";"
                "p.dispatchEvent(new Event('input',{bubbles:true}));"
                "document.querySelector('[data-action=\"signin-submit\"]').click();"
                "return 1;})()")
            await asyncio.sleep(2.5)
            await cdp.js(HELPERS)
            check("signed in as superadmin",
                  await cdp.js("window.__has('superadmin')"))

            check("page title correct",
                  await cdp.js("document.title") == "Lextria IP Dashboard")
            check("app rendered into #app-root",
                  await cdp.js("document.getElementById('app-root').children.length > 0"))
            check("CSS applied (external stylesheet loaded)",
                  await cdp.js("getComputedStyle(document.body).fontFamily.indexOf('Public Sans') !== -1"))
            check("logo loaded from /static",
                  await cdp.js("(function(){var i=document.querySelector('img.brand-logo');"
                               "return !!i && i.complete && i.naturalWidth>0;})()"))
            for t in ("trademark", "copyright", "design"):
                check("%s tab present" % t,
                      await cdp.js("!!document.querySelector('[data-iptype=\"%s\"]')" % t))
            check("stats row rendered",
                  await cdp.js("window.__has('Total applications')"))

            print("\n--- 2. Add a TRADEMARK through the UI ---", flush=True)
            await add_matter(cdp, "trademark", "ACMEBRAND", "TM-99001",
                             "__new__", "Acme Innovations Ltd")
            check("trademark appears in the ledger",
                  await cdp.js("window.__has('ACMEBRAND')"))
            check("new client was created",
                  await cdp.js("window.__has('Acme Innovations Ltd')"))

            print("\n--- 3. Add a COPYRIGHT through the UI ---", flush=True)
            await add_matter(cdp, "copyright", "The Acme Handbook", "CR-4402", "c-1")
            check("copyright appears in the ledger",
                  await cdp.js("window.__has('Acme Handbook')"))
            check("copyright shows its own 'Diary Number' column",
                  await cdp.js("window.__has('Diary Number')"))

            print("\n--- 4. Add a DESIGN through the UI ---", flush=True)
            await add_matter(cdp, "design", "Contour Bottle", "DS-7781", "c-1")
            check("design appears in the ledger",
                  await cdp.js("window.__has('Contour Bottle')"))
            check("design shows its own 'Locarno Class' column",
                  await cdp.js("window.__has('Locarno Class')"))

            print("\n--- 5. Reload the page: does it come back from the server? ---", flush=True)
            await cdp.send("Page.navigate", url=base + "/")
            await asyncio.sleep(3.0)
            await cdp.js(HELPERS)
            check("session survived reload (no sign-in screen)",
                  await cdp.js("!document.getElementById('signin-user')"))
            check("trademark survived reload",
                  await cdp.js("window.__has('ACMEBRAND')"))
            check("client survived reload",
                  await cdp.js("window.__has('Acme Innovations Ltd')"))
            await cdp.js("window.__tab('copyright')")
            await asyncio.sleep(0.6)
            check("copyright survived reload",
                  await cdp.js("window.__has('Acme Handbook')"))
            await cdp.js("window.__tab('design')")
            await asyncio.sleep(0.6)
            check("design survived reload",
                  await cdp.js("window.__has('Contour Bottle')"))

            errs = await cdp.js("JSON.stringify(window.__errors || [])")
            check("no uncaught JS errors", errs in ("[]", None), errs)

        print("\n--- 6. Did it really reach SQLite on disk? ---", flush=True)
        check("database file created", db_file.exists(), str(db_file))
        if db_file.exists():
            conn = sqlite3.connect(str(db_file))
            row = conn.execute(
                "SELECT document, revision FROM ledger_state WHERE id=1").fetchone()
            hist = conn.execute("SELECT COUNT(*) FROM ledger_history").fetchone()[0]
            conn.close()
            check("ledger row present", row is not None)
            if row:
                doc = json.loads(row[0])
                recs = doc.get("records", [])
                brands = sorted(r.get("brand", "") for r in recs)
                types = sorted(r.get("ipType", "") for r in recs)
                check("3 records stored", len(recs) == 3, brands)
                check("all three ipTypes stored",
                      types == ["copyright", "design", "trademark"], types)
                check("brands stored correctly",
                      brands == ["ACMEBRAND", "Contour Bottle", "The Acme Handbook"], brands)
                check("client stored",
                      any(c.get("name") == "Acme Innovations Ltd"
                          for c in doc.get("clients", [])), doc.get("clients"))
                check("audit log written",
                      len(doc.get("log", [])) >= 3, len(doc.get("log", [])))
                check("revision advanced past 1", row[1] >= 3, row[1])
                check("revision history archived", hist >= 2, hist)
    finally:
        if browser is not None:
            browser.terminate()
        server.terminate()
        try:
            server.wait(timeout=10)
        except Exception:
            server.kill()
        shutil.rmtree(profile, ignore_errors=True)
        shutil.rmtree(tmpdir, ignore_errors=True)

    passed = sum(1 for _, ok in results if ok)
    failed = [n for n, ok in results if not ok]
    print("\n" + "=" * 64)
    print("  %d/%d checks passed" % (passed, len(results)))
    if failed:
        print("  FAILED: " + ", ".join(failed))
    print("=" * 64)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(run()))
