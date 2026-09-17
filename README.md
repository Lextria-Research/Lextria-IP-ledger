# Lextria IP Ledger

A dashboard for tracking an IP firm's **trademark, copyright and design**
matters — clients, application numbers, statuses, deadlines, applicants,
authors and contributors, per-matter financials, CSV/JSON import and export,
and a per-matter audit timeline.

The front end is one self-contained `index.html` with no build step. The
backend is a small FastAPI app that owns accounts, roles and storage.

---

## Quick start

```bash
pip install -r backend/requirements.txt
py -m uvicorn backend.main:app --reload
```

Then open <http://localhost:8000>.

On the very first run the server creates a `superadmin` account and prints its
**access key** once:

```
========================================================================
  Superadmin account created (key shown once - only its hash is stored)

      username:  superadmin
      key:       lx_kQ8xn2_Vr4Ts9mPqW2eR7uYbNcFdGhJk

  Sign in with that key. If it is lost, issue a new one with:
      py -m backend.manage rotate superadmin
========================================================================
```

Copy that key somewhere safe (a password manager) before closing the
terminal — it cannot be shown again, because only its hash is stored. Sign in
with it, then add accounts from **Settings → Accounts**.

### There are no passwords

Every account authenticates with its own **access key** — a long random
value the server generates, shown to whoever creates the account exactly
once. Nobody chooses or types a password anywhere in this app.

- **Signing in from a browser**: the key is traded once, at `POST
  /api/login`, for an HttpOnly session cookie. The key itself never has to
  sit in page storage where a script could read it back out.
- **Calling the API directly** (a script, a curl command): send the key on
  every request, as `Authorization: Bearer <key>` or `X-Lextria-Key: <key>`.
  No session, no cookie, nothing to expire mid-script.

A key can be replaced (**Settings → Your account → Issue a new key**, or a
super admin can reissue anyone's from **Settings → Accounts**) if it may have
leaked or was simply lost. Replacing a key ends every session that was opened
with the old one, immediately.

---

## The three roles

| | Super admin | Trademark admin | Drafter |
|---|---|---|---|
| See matters | all | all | only those assigned to them |
| **Financials** (fees, invoices, payment status) | **yes** | **no** | **no** |
| Create / edit / delete matters | yes | yes | no |
| Change status, set next action & deadline | yes | yes | yes |
| Assign matters to a drafter | yes | yes | no |
| Manage clients | yes | yes | no |
| Import / export | yes | yes | no |
| Clear all / de-duplicate | yes | no | no |
| Manage accounts | yes | no | no |

All three roles work across **all three IP types**. "Trademark admin" is the
job title, not a restriction to trademarks — that role administers copyright
and design matters too. What separates it from a super admin is financial
data and account management, not subject matter.

### What "cannot see financial data" actually means

It is not a hidden field. `GET /api/state` **removes** `officialFee`,
`professionalFee`, `amountPaid`, `paymentStatus`, `invoiceRef`, `currency` and
`feeNotes` from the JSON before it is sent, so those values never reach the
browser of anyone but a super admin. Open dev tools as a trademark admin and
there is simply nothing there to find.

Three consequences follow, and all three are enforced in
[`backend/roles.py`](backend/roles.py):

1. **A filtered read cannot be written back literally.** A drafter is sent only
   their own matters; applying their save as-is would delete every other matter
   in the firm. Every save from a restricted role is a *merge* onto the stored
   document, never a replace.
2. **Absent fee values are not blanks.** A trademark admin's save carries no
   fee keys at all, so the stored values are carried forward rather than
   overwritten with nothing.
3. **The audit log gets the same treatment.** "Set professional fee to 25,000"
   would hand back the number that was just stripped, so log entries flagged as
   financial are withheld too — and the flag is recomputed from the saver's
   role, so a client cannot forge or strip it.

The UI hides controls a role lacks, but that is only to stop a pointless
click. **Never move an access decision into `index.html`** — anything that page
receives can be read out of it.

---

## Accounts

From **Settings → Accounts**, a super admin can add accounts, change roles,
suspend or restore them, reissue a key, and delete accounts. Adding an account
shows its brand-new key exactly once, right there in the panel — copy it
before navigating away or reloading. Changing a role, suspending an account,
or reissuing its key all end that account's sessions immediately, so the
change takes effect on the next request rather than whenever the cookie
happens to expire.

Suspending or deleting someone also clears their matter assignments — an
assignment to an account that no longer exists is invisible to every drafter
with no signal anywhere else.

The last active super admin cannot be deleted or demoted, from the UI or the
CLI. Without that guard an installation can be left with nobody able to manage
users or see financial data.

### The command line

The way back in when nobody can sign in:

```bash
py -m backend.manage list
py -m backend.manage add rakesh trademark_admin
py -m backend.manage rotate rakesh
py -m backend.manage role rakesh superadmin
py -m backend.manage suspend rakesh
py -m backend.manage activate rakesh
py -m backend.manage delete rakesh
```

`add` and `rotate` print the new key to the terminal exactly once. There is
nowhere else to read it from afterward.

---

## Security

**There are no passwords.** Every account authenticates with its own access
key — 256 bits from Python's `secrets` module, shown once when issued and
stored only as a SHA-256 hash. A key is either traded once for a session
cookie (the browser) or sent on every request as `Authorization: Bearer
<key>` / `X-Lextria-Key: <key>` (a script). Because the key is already random
and that long, a fast hash is the right tool: key-stretching algorithms like
PBKDF2 or bcrypt exist to slow down guessing a short, human-chosen password,
and there is no such guessable thing here to protect.

A key on the request headers is checked first and takes priority over any
session cookie present — a wrong key is always an error, never silently
ignored in favour of a cookie that happens to be on the request. That is what
stops a script that believes it is acting as one account from silently
acting as another.

**Sessions** are random 32-byte tokens in an `HttpOnly`, `SameSite=Strict`
cookie, valid 12 hours. `HttpOnly` means script on the page cannot read it, so
an XSS cannot steal it; `SameSite=Strict` means it is not sent cross-site,
which is what blocks CSRF. The cookie is marked `Secure` automatically when the
connection is HTTPS (directly or via `X-Forwarded-Proto`).

**Rate limiting** is per source address, in memory: 20 attempts per 5
minutes, whatever key was tried. There is no per-account lockout, because a
256-bit key cannot meaningfully be guessed — a wrong key names no account to
lock in the first place. What the per-address limit still catches is one
address hammering the key check at speed, which keeps logs, CPU and the
login history from being flooded.

A failed sign-in returns the same message whether the key is simply unknown
or belongs to a suspended account, so neither can be told apart from outside.

**Login history** (`Settings`, super admin only) records every attempt with its
source address. The lockout stops an attack; this is what lets someone *see*
that one happened.

**Request hardening** (`backend/security.py`):

- The `Host` header must be `localhost` or a bare IP. Binding to localhost does
  not by itself keep a browser-based attacker out: in a DNS-rebinding attack a
  page re-resolves its own domain to 127.0.0.1 and the victim's browser then
  makes same-origin requests here — while sending `Host: evil.example.com`.
  Rejecting domain names breaks that at its one observable tell.
- `PUT /api/state` is capped at 8 MB, enforced while streaming (a chunked
  request declares no `Content-Length`).
- A strict CSP with a **per-response nonce**. The page keeps its single inline
  script, but `script-src` is `'self' 'nonce-…'` rather than `'unsafe-inline'`,
  so an injected `<script>` will not run — it cannot guess a value that is
  regenerated on every response.
- `X-Content-Type-Options`, `X-Frame-Options`, `Referrer-Policy: no-referrer`,
  `Cache-Control: no-store`, `Permissions-Policy`, COOP/CORP, and HSTS (inert
  on plain HTTP, live the moment TLS is in front).

Interactive API docs are disabled. On an app whose main endpoint replaces the
firm's ledger, Swagger UI is a ready-made "Try it out" button.

### Before putting this on a network

The defaults assume localhost. To serve it to the firm:

- Put it behind a reverse proxy that **terminates TLS**. Session cookies over
  plain HTTP are readable in transit.
- The proxy will send a real `Host` header, which `host_is_safe` rejects by
  design. Terminate at the proxy and let it own access control, or relax that
  check deliberately — do not remove it and forget why it was there.
- Back up `backend/lextria.db`. It holds every account and every matter.

---

## Concurrency

The client holds the ledger as one JSON document and sends the whole thing on
every save, so two people saving moments apart could trivially overwrite each
other. Every save carries an `X-Ledger-Revision` header naming the version it
was based on, and the server three-way merges **baseline** (what the saver last
loaded) against **stored** (what is there now) and **incoming** (what they are
sending). That distinguishes:

- a deliberate edit or delete,
- someone else's concurrent edit, which must not be reverted just because this
  saver's copy predates it,
- two people creating a new matter at the same moment and landing on the same
  id — the second is re-filed under a fresh id and the client is told, via
  `idRemap`, rather than one of the two matters being destroyed.

---

## API

| Method | Path | Who |
|---|---|---|
| POST | `/api/login` | anyone — `{key}` in, a session cookie out |
| POST | `/api/logout` | anyone |
| GET | `/api/me` | anyone (key header or cookie) |
| GET | `/api/state` | signed in — filtered by role |
| PUT | `/api/state` | signed in — merged by role |
| POST | `/api/key/rotate` | signed in — replace your own key |
| POST | `/api/sessions/revoke-others` | signed in |
| GET | `/api/assignees` | can assign matters |
| GET | `/api/users` · POST · PATCH · DELETE `/api/users/{id}` | super admin |
| POST | `/api/users/{id}/rotate-key` | super admin — reissue someone's key |
| GET | `/api/login-history` | super admin |
| GET | `/api/health` | anyone |

Every endpoint above except `/api/login`, `/api/logout` and `/api/health`
accepts either an `X-Lextria-Key`/`Authorization: Bearer` header or a session
cookie — whichever is present. A key on the headers is always checked first.

---

## Storage

One SQLite file, `backend/lextria.db`, holding accounts, sessions and the
ledger, in WAL mode so a slow save does not block dashboard reads. The last 50
revisions of the ledger are kept in `ledger_history` — not exposed through the
API, but it means a bad import or an accidental "clear all" is recoverable by
hand, and it is what the three-way merge compares against.

If the server is unreachable, the page falls back to `localStorage` and works
as a single-user ledger in that browser. There are no accounts and no roles in
that mode, because there is no server to enforce them.

---

## Database migrations

`backend/db.py:init_db()` and `backend/auth.py:init_auth_schema()` create the
schema with `CREATE TABLE IF NOT EXISTS` on every startup, so **a fresh
install needs nothing extra** — `py -m uvicorn backend.main:app` alone is
enough, with or without Alembic ever having been run. Alembic sits alongside
that, not in front of it, so that any *future* schema change (an `ALTER
TABLE`, a new column) has a migration chain to attach to, instead of being a
second, undocumented edit to those `CREATE TABLE` strings.

```bash
pip install -r backend/requirements.txt   # pulls in alembic + SQLAlchemy
py -m alembic upgrade head                # apply every migration
py -m alembic current                     # what this database thinks it's at
```

`alembic/env.py` points at the exact same file `backend/db.py:DB_PATH`
resolves — never a second, hardcoded path in `alembic.ini` that could drift
out of sync with it.

The one migration so far, `alembic/versions/5d06663f5855_*.py`, is a
**baseline**, not a change: it recreates — verbatim, via raw SQL — the schema
the app already builds itself. Two situations, two different commands:

- **A fresh database** (no `backend/lextria.db` yet): `alembic upgrade head`
  creates every table outright. The `IF NOT EXISTS` guards make this safe even
  if the app happened to run first and already created them.
- **An existing installation** whose database predates Alembic: the app has
  already created every table. Run `alembic stamp head` instead — it marks
  the baseline satisfied without re-running its SQL or touching a row of
  existing data.

Adding a real schema change later means a new revision, chained onto this one:

```bash
py -m alembic revision -m "add a widgets table"
# hand-write the upgrade()/downgrade() in the new file under alembic/versions/,
# using op.execute() with raw SQL -- there is no ORM layer here to autogenerate from
py -m alembic upgrade head
```

`tests/test_migrations.py` checks both orderings above against a throwaway
database on every test run, so a schema drift between the migration and
`init_db()`/`init_auth_schema()` fails the suite rather than surfacing as a
confusing error on someone else's install.

---

## Tests

```bash
py -m pytest tests -q
```

Covers access-key generation and hashing, session handling, the per-address
rate limiter, key rotation (self-service and admin-issued), header-based
authentication (`Authorization: Bearer` and `X-Lextria-Key`), the role
matrix, financial redaction across all three IP types, the merge rules
(including concurrent edits and id collisions), the HTTP permission surface,
and the hardening middleware. `tests/test_frontend_contract.py` additionally
checks `index.html` against the server — the two share a financial-field list
and a drafter-editable-field list, and nothing else would notice them drifting
apart. `tests/test_migrations.py` checks the Alembic baseline against
`init_db()`/`init_auth_schema()` the same way.

Run the full suite before changing anything in `backend/roles.py`. Every rule
in the table at the top of this file has a test, and that is the only thing
standing between a refactor and a fee ending up in the wrong person's browser.
