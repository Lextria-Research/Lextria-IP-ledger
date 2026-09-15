"""End-to-end demo flow, driven with Playwright, for recording a walkthrough video.

Spins up the real FastAPI backend against a throwaway SQLite database, opens a
headed Chromium window (with video recording turned on), and drives the whole
app in one uninterrupted run:

  sign in as superadmin -> add a trademark, a copyright and a design (random
  data) -> edit a record -> record a stage transition (audit history) ->
  sign out -> sign in as trademark_admin -> add another matter, edit a
  financial field -> sign out -> sign in as drafter -> view the ledger with
  financial fields hidden -> sign out.

The mouse moves in short eased, slightly wobbly paths between clicks (not
teleporting to elements) so it reads as a human driving the app. No manual
pauses between steps -- it's meant to be screen-recorded start to finish.
A .webm video is saved under tests/videos/ when it's done.

Setup (one-time):   py -m pip install playwright && py -m playwright install chromium
Run:                 py tests/e2e_playwright_demo.py
"""

import random
import shutil
import socket
import string
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import requests
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

ADMIN_PW = "e2e-Demo-" + "".join(random.choices(string.ascii_letters + string.digits, k=8))
TM_ADMIN_PW = "e2e-Demo-" + "".join(random.choices(string.ascii_letters + string.digits, k=8))
DRAFTER_PW = "e2e-Demo-" + "".join(random.choices(string.ascii_letters + string.digits, k=8))
VIDEO_DIR = ROOT / "tests" / "videos"


def free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def rand_str(prefix, n=6):
    return prefix + "-" + "".join(random.choices(string.ascii_uppercase + string.digits, k=n))


def rand_company():
    adjectives = ["Acme", "Nimbus", "Vertex", "Orbit", "Cobalt", "Lumen", "Granite", "Solace"]
    nouns = ["Innovations", "Holdings", "Ventures", "Labs", "Industries", "Group", "Partners"]
    return "%s %s %s" % (random.choice(adjectives), random.choice(nouns),
                          random.choice(["Pvt. Ltd.", "LLP", "Ltd.", "Inc."]))


def rand_brand():
    words = ["Falcon", "Nova", "Zephyr", "Ember", "Quartz", "Wren", "Halo", "Drift", "Cedar", "Pulse"]
    return random.choice(words) + random.choice(["", "X", "Pro", "One", "Max"])


_mouse_pos = [200, 200]


def human_move(page, x, y):
    """Move the mouse to (x, y) through a slightly wobbly multi-step path,
    the way a person's hand does, instead of teleporting there."""
    sx, sy = _mouse_pos
    steps = random.randint(14, 22)
    for i in range(1, steps + 1):
        t = i / steps
        ease = t * t * (3 - 2 * t)  # smoothstep easing
        wob_x = random.uniform(-4, 4) * (1 - t)
        wob_y = random.uniform(-4, 4) * (1 - t)
        page.mouse.move(sx + (x - sx) * ease + wob_x, sy + (y - sy) * ease + wob_y)
        page.wait_for_timeout(random.randint(6, 16))
    page.mouse.move(x, y)
    _mouse_pos[0], _mouse_pos[1] = x, y


def human_click(page, selector):
    el = page.locator(selector).first
    el.scroll_into_view_if_needed()
    box = el.bounding_box()
    if box is not None:
        # Wander towards the element's neighbourhood first, purely for the
        # human-looking cursor trail -- the real click below re-checks the
        # element's live position so a reflow during the wander can't cause
        # the click to land on the wrong, since-shifted element.
        x = box["x"] + box["width"] * random.uniform(0.35, 0.65)
        y = box["y"] + box["height"] * random.uniform(0.35, 0.65)
        human_move(page, x, y)
        page.wait_for_timeout(random.randint(60, 140))
    el.click()
    if box is not None:
        _mouse_pos[0], _mouse_pos[1] = box["x"] + box["width"] / 2, box["y"] + box["height"] / 2


def human_type(page, selector, text):
    el = page.locator(selector).first
    human_click(page, selector)
    el.fill("")
    for ch in text:
        el.type(ch, delay=random.randint(35, 90))


def set_field(page, name, value):
    human_type(page, '[data-field="%s"]' % name, str(value))


def select_field(page, name, value):
    human_click(page, '[data-field="%s"]' % name)
    page.select_option('[data-field="%s"]' % name, value)


def click_action(page, action, **attrs):
    sel = '[data-action="%s"]' % action
    for k, v in attrs.items():
        sel += '[%s="%s"]' % (k, v)
    human_click(page, sel)


def main():
    port = free_port()
    tmpdir = Path(tempfile.mkdtemp(prefix="lex_pw_demo_db_"))
    db_file = tmpdir / "demo.db"
    (tmpdir / "demo_app.py").write_text(
        "import pathlib, sys\n"
        "sys.path.insert(0, r'%s')\n"
        "from backend import db\n"
        "db.DB_PATH = pathlib.Path(r'%s')\n"
        "from backend.main import app\n" % (ROOT, db_file),
        encoding="utf-8",
    )

    base = "http://127.0.0.1:%d" % port
    print("Starting backend on %s (throwaway database)..." % base)
    server = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "demo_app:app", "--port", str(port)],
        cwd=str(tmpdir), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
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
            raise RuntimeError("backend did not start in time")

        from backend import db as _db
        _db.DB_PATH = db_file
        from backend import auth as _auth
        _auth.set_password("superadmin", ADMIN_PW)
        _auth.create_user("demo.trademark_admin", TM_ADMIN_PW, "trademark_admin")
        _auth.create_user("demo.drafter", DRAFTER_PW, "drafter")

        VIDEO_DIR.mkdir(parents=True, exist_ok=True)

        with sync_playwright() as p:
            browser = p.chromium.launch(headless=False, slow_mo=60)
            context = browser.new_context(
                viewport={"width": 1600, "height": 900},
                record_video_dir=str(VIDEO_DIR),
                record_video_size={"width": 1600, "height": 900},
            )
            context.set_default_timeout(15000)
            page = context.new_page()

            def sign_in(username, password):
                page.goto(base + "/")
                page.wait_for_selector("#signin-user")
                human_type(page, "#signin-user", username)
                human_type(page, "#signin-pass", password)
                click_action(page, "signin-submit")
                page.wait_for_selector('[data-action="set-mode"][data-mode="ledger"]')
                click_action(page, "set-mode", **{"data-mode": "ledger"})
                page.wait_for_selector('[data-action="set-iptype"][data-iptype="trademark"]')

            def sign_out():
                click_action(page, "sign-out")
                page.wait_for_selector("#signin-user")

            # ---- sign in as superadmin ----
            sign_in("superadmin", ADMIN_PW)

            created = {}

            # ---- trademark ----
            click_action(page, "set-iptype", **{"data-iptype": "trademark"})
            click_action(page, "open-add")
            page.wait_for_selector('[data-field="clientId"]')
            select_field(page, "clientId", "__new__")
            client_name = rand_company()
            set_field(page, "newClientName", client_name)
            brand = rand_brand()
            set_field(page, "brand", brand)
            set_field(page, "appno", rand_str("TM"))
            click_action(page, "save-record")
            page.wait_for_timeout(800)
            created["trademark"] = brand

            # ---- copyright ----
            click_action(page, "set-iptype", **{"data-iptype": "copyright"})
            click_action(page, "open-add")
            page.wait_for_selector('[data-field="clientId"]')
            options = page.eval_on_selector_all(
                '[data-field="clientId"] option', "els => els.map(e => e.value)")
            real_clients = [o for o in options if o and o != "__new__"]
            select_field(page, "clientId", real_clients[0] if real_clients else "__new__")
            cr_title = "The " + rand_brand() + " Handbook"
            set_field(page, "brand", cr_title)
            set_field(page, "appno", rand_str("CR"))
            click_action(page, "save-record")
            page.wait_for_timeout(800)
            created["copyright"] = cr_title

            # ---- design ----
            click_action(page, "set-iptype", **{"data-iptype": "design"})
            click_action(page, "open-add")
            page.wait_for_selector('[data-field="clientId"]')
            options = page.eval_on_selector_all(
                '[data-field="clientId"] option', "els => els.map(e => e.value)")
            real_clients = [o for o in options if o and o != "__new__"]
            select_field(page, "clientId", real_clients[0] if real_clients else "__new__")
            ds_name = rand_brand() + " Bottle"
            set_field(page, "brand", ds_name)
            set_field(page, "appno", rand_str("DS"))
            click_action(page, "save-record")
            page.wait_for_timeout(800)
            created["design"] = ds_name

            # ---- edit the trademark record ----
            click_action(page, "set-iptype", **{"data-iptype": "trademark"})
            row = page.locator('tr.row[data-action="toggle-expand"]', has_text=brand).first
            record_id = row.get_attribute("data-id")
            click_action(page, "open-edit", **{"data-id": record_id})
            page.wait_for_selector('[data-field="action"]')
            set_field(page, "action", "Reviewed and updated during demo walkthrough on "
                      + time.strftime("%Y-%m-%d"))
            click_action(page, "save-record")
            page.wait_for_timeout(800)

            # ---- stage transition / audit history ----
            click_action(page, "open-edit", **{"data-id": record_id})
            page.wait_for_selector('[data-field="status"]')
            status_options = page.eval_on_selector_all(
                '[data-field="status"] option', "els => els.map(e => e.value)")
            current_status = page.eval_on_selector('[data-field="status"]', "el => el.value")
            other_statuses = [s for s in status_options if s and s != current_status]
            if other_statuses:
                select_field(page, "status", random.choice(other_statuses))
                page.wait_for_timeout(400)
                if page.locator('[data-field="stageRemarks"]').count():
                    set_field(page, "stageRemarks",
                              "Stage transition recorded automatically for demo purposes.")
                if page.locator('[data-action="commit-stage-transition"]').count():
                    click_action(page, "commit-stage-transition")
                    page.wait_for_timeout(600)
                else:
                    click_action(page, "save-record")
                    page.wait_for_timeout(600)
            else:
                click_action(page, "close-modal")

            # ---- view the audit / stage-transition history for this record ----
            click_action(page, "toggle-expand", **{"data-id": record_id})
            page.wait_for_timeout(700)

            sign_out()

            # ---- sign in as trademark_admin: add a matter, edit financials ----
            sign_in("demo.trademark_admin", TM_ADMIN_PW)
            click_action(page, "set-iptype", **{"data-iptype": "trademark"})
            click_action(page, "open-add")
            page.wait_for_selector('[data-field="clientId"]')
            options = page.eval_on_selector_all(
                '[data-field="clientId"] option', "els => els.map(e => e.value)")
            real_clients = [o for o in options if o and o != "__new__"]
            select_field(page, "clientId", real_clients[0] if real_clients else "__new__")
            tm2_brand = rand_brand()
            set_field(page, "brand", tm2_brand)
            set_field(page, "appno", rand_str("TM"))
            click_action(page, "save-record")
            page.wait_for_timeout(800)
            created["trademark_admin_added"] = tm2_brand

            row2 = page.locator('tr.row[data-action="toggle-expand"]', has_text=brand).first
            click_action(page, "open-edit", **{"data-id": row2.get_attribute("data-id")})
            page.wait_for_timeout(600)
            if page.locator('[data-field="officialFee"]').count():
                set_field(page, "officialFee", str(random.randint(1000, 9000)))
            # Assign this matter to the drafter -- a drafter only ever sees
            # matters assigned to them (backend/roles.py), so without this
            # the drafter's ledger below would simply be empty.
            if page.locator('[data-field="assignedTo"]').count():
                if page.eval_on_selector('[data-field="assignedTo"]', "el => el.tagName") == "SELECT":
                    select_field(page, "assignedTo", "demo.drafter")
                else:
                    set_field(page, "assignedTo", "demo.drafter")
            click_action(page, "save-record")
            page.wait_for_timeout(800)

            sign_out()

            # ---- sign in as drafter, show restricted financial view ----
            sign_in("demo.drafter", DRAFTER_PW)
            click_action(page, "set-iptype", **{"data-iptype": "trademark"})
            page.wait_for_timeout(800)
            drafter_rows = page.locator('tr.row[data-action="toggle-expand"]', has_text=brand)
            if drafter_rows.count():
                click_action(page, "toggle-expand",
                             **{"data-id": drafter_rows.first.get_attribute("data-id")})
                page.wait_for_timeout(700)
            else:
                page.wait_for_timeout(500)

            sign_out()

            print("Demo flow complete. Records created: %s" % created)
            context.close()
            browser.close()

    finally:
        server.terminate()
        try:
            server.wait(timeout=10)
        except Exception:
            server.kill()
        shutil.rmtree(tmpdir, ignore_errors=True)

    print("Video saved under: %s" % VIDEO_DIR)


if __name__ == "__main__":
    main()
