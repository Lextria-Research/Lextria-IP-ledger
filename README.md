# Lextria IP Ledger

A dashboard for tracking an IP law firm's **trademark**, **copyright** and
**design** matters — clients, application numbers, statuses, deadlines,
applicants and authors, per-matter fees, plus CSV/XLSX/JSON import and export.

Plain HTML/CSS/JS with no build step, served by a small **FastAPI + SQLite**
backend that also holds the accounts and enforces who may see what.

## What it covers

Each IP type is a first-class module with its own examination pipeline, field
labels and deadline rules:

| | Trademark | Copyright | Design |
|---|---|---|---|
| Title field | Brand / mark | Title of Work | Design Title |
| Classification | Class | Category of Work (8 statutory categories) | Locarno Class |
| Application no. | Application no. | Diary Number | Application No. |
| Pipeline stages | 10 | 10 | 9 |
| Renewal | 10-year term | none (statutory term) | 10-year term |
| People | Applicants | Applicants + Authors | Applicants + Contributors |

There is **no patent module** — patents are not tracked by this app.

Stage changes carry statutory SLA offsets (30 days to answer a trademark
examination report, 180 days for a design FER response, and so on), so setting
a status suggests the matching deadline.

## Quick start

Requires Python 3.9+. Run from the repository root.

On Windows (the `py` launcher ships with Python and is usually on PATH even
when `python` is not):

```powershell
py -m pip install -r backend/requirements.txt
py -m uvicorn backend.main:app --reload
```

On macOS / Linux:

```bash
python3 -m pip install -r backend/requirements.txt
python3 -m uvicorn backend.main:app --reload
```

Then open <http://127.0.0.1:8000>.

**On the very first run** the server creates a `superadmin` account and prints
its password to the console **once**:

```
====================================================================
  Superadmin account created (shown once - only its hash is stored)

      username:  superadmin
      password:  <random>
====================================================================
```

Only the hash is stored, so that password cannot be recovered — just reset
(see below). Sign in with it and change it in **Settings → Your account**.

### No environment variables

The app needs none. No `.env`, no API key, no external service. Accounts,
sessions and the ledger all live in one SQLite file created on first run at
`backend/lextria.db` (git-ignored). To back up everything, copy that file; to
start over, delete it.

## Roles

Every account has one of three roles. **The rules are enforced on the server**,
in `backend/roles.py` — the browser is told what to hide only as a convenience,
because anything sent to a browser can be read out of it with dev tools.

| | Super admin | Trademark admin | Drafter |
|---|---|---|---|
| See all matters | ✅ | ✅ | only those assigned to them |
| Per-matter financials | ✅ | ❌ never sent | ❌ never sent |
| Create / edit / delete matters | ✅ | ✅ | ❌ |
| Change status and deadlines | ✅ | ✅ | ✅ on their own matters |
| Import / export | ✅ | ✅ | ❌ |
| Manage clients | ✅ | ✅ | ❌ |
| Manage accounts | ✅ | ❌ | ❌ |

Two consequences worth understanding:

- **Financial values are stripped from the payload**, not hidden in the page. A
  trademark admin's browser never receives a fee, so it cannot leak one.
- **A restricted save is merged, not applied.** The client PUTs the whole
  ledger; a drafter who can see one matter would otherwise wipe every other
  matter in the firm on their first save. The server applies only the changes
  that role is allowed to make, onto the stored document.

### Assignment

A drafter sees a matter only when it is **assigned to them**. Set that in the
matter's *Assigned to* dropdown, which lists active accounts. Until a matter is
assigned, no drafter can see it.

### Audit trail

Stage changes and edits are recorded in the **Log**, and each matter keeps its
own timeline. Entries made by a drafter are generated **server-side** and
stamped with the server's clock and the signed-in username, so history cannot
be backdated or attributed to someone else.

## Managing accounts

From the app: **Settings → People and access** (super admin only) — add, suspend,
restore or remove accounts. Suspending ends that person's sessions immediately.

From the command line:

```powershell
py -m backend.manage list
py -m backend.manage add <username> <role>    # roles: superadmin, trademark_admin, drafter
py -m backend.manage passwd <username>        # reset a forgotten password
py -m backend.manage delete <username>
```

Changing a password signs that account out everywhere — including after an
admin reset, which is the point of resetting it.

**Locked out?** Five wrong passwords locks an account for five minutes. Wait, or
clear it:

```powershell
py -c "from backend import auth; auth._clear_failures('superadmin')"
```

## Security — what is real and what is not

### The shape of it

Accounts and roles are real, server-enforced access control. What follows is
about the network the server sits on.

- **Bound to localhost** (the default): only your own machine can reach it.
- **Bound to `0.0.0.0`**: everyone on your network can reach the sign-in page.
  They still need an account — but the traffic is plain HTTP, so put a
  TLS-terminating reverse proxy in front of it before doing this with real
  client data.
- **On the public internet**: only behind a reverse proxy with TLS.

Teammates reach a network-bound server at `http://<your-ip>:8000` — **by IP
address, not machine name**. Hostnames are refused with HTTP 421; see DNS
rebinding below.

### What the backend enforces

In `backend/security.py` and `backend/auth.py`, covered by `tests/`:

- **Passwords** are PBKDF2-HMAC-SHA256, 600,000 iterations, per-user salt.
- **Sessions** are HttpOnly, SameSite=strict cookies, 12 hours, and are ended by
  a password change, a suspension, a role change or account deletion. The
  `Secure` flag is set automatically when served over HTTPS.
- **Login throttling**: 5 failures locks that account for 5 minutes.
- **DNS rebinding is blocked.** Binding to localhost is not by itself enough — a
  malicious site can re-point its own domain at 127.0.0.1 and have your browser
  read the ledger. Only `localhost` and bare IPs are accepted as `Host`.
- **Request bodies are capped** at 8 MB.
- **No interactive API docs** — Swagger on this API would be a point-and-click
  ledger overwrite.
- **Only `static/` is served.** `backend/` (including the database) and `.git/`
  are unreachable over HTTP.
- **Security headers** on every response, including a CSP with a strict
  `script-src 'self'` (the page keeps its JavaScript in a file, not inline).

### What is not protection

- **The old on-page passphrase** (Settings → Login passphrase) is a UI deterrent
  only, and is now redundant — it predates real accounts.
- **Anyone else with an account on your machine** can reach a localhost-bound
  server.
- **Traffic is plain HTTP** unless you put TLS in front of it.
- Keep the repository **private** if you commit real matter data.
  `backend/lextria.db` is git-ignored precisely so live data never lands in git.

## API

| Method | Path | Notes |
|---|---|---|
| `POST` | `/api/login` | sets the session cookie |
| `POST` | `/api/logout` | |
| `GET` | `/api/me` | `{signedIn, username, role, can[]}` |
| `POST` | `/api/password` | change your own; needs the current one |
| `GET` | `/api/state` | the ledger, filtered for your role |
| `PUT` | `/api/state` | merges the changes your role may make |
| `GET` | `/api/assignees` | active accounts, for the assignment dropdown |
| `GET/POST` | `/api/users` | super admin only |
| `PATCH/DELETE` | `/api/users/{id}` | super admin only; suspend, change role, remove |
| `GET` | `/api/health` | |

Each replaced ledger version is archived in a `ledger_history` table (last 50
revisions). It is not exposed through the API, but a bad import is recoverable
by hand with `sqlite3 backend/lextria.db`.

## Tests

```powershell
py -m pip install pytest
py -m pytest tests/ -q          # API, roles, hardening, accounts
py tests\e2e_browser.py         # drives the real UI over the DevTools Protocol
py tests\demo_roles.py          # Playwright walkthrough of all three roles
py tests\demo_roles.py --headed # ...in a visible browser
```

The two browser scripts start their own server on a spare port with a
throwaway database, so they never touch your real ledger.

## Project layout

```
index.html                     HTML shell — markup and asset tags only
static/css/app.css             all styles
static/js/app.js               all application code
static/img/lextria-logo.png    brand mark
backend/main.py                FastAPI app: routes, middleware, page serving
backend/auth.py                accounts, password hashing, sessions, throttling
backend/roles.py               what each role may see and change
backend/security.py            Host validation, body cap, response headers
backend/db.py                  SQLite persistence + revision history
backend/manage.py              command-line account management
tests/                         pytest suites and the two browser drivers
```

No build step — the browser loads the three front-end files directly. Only
`static/` is reachable over HTTP.

The one place the split matters is the Claude artifact tier, which must publish
a single self-contained file: `buildFullDocument()` in `static/js/app.js`
fetches the CSS, JS and logo back and inlines them, so if you move any of those
three, update `ASSET_CSS` / `ASSET_JS` / `ASSET_LOGO` near the top of that file.

## Starter data

The ledger ships **empty**. The starting state is embedded in `index.html`:

```html
<script id="app-state" type="application/json">{"clients": [], "records": [], ...}</script>
```

It is used only the first time a browser or backend has nothing saved. To ship
sample clients instead, edit that JSON block following the shape of a record
created through the UI.
