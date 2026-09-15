"""FastAPI backend for the Lextria IP Ledger.

There is no environment configuration of any kind: accounts, sessions and the
ledger all live in one SQLite file next to this module.

  POST /api/login    -> sets an HttpOnly session cookie
  POST /api/logout
  GET  /api/me       -> {signedIn, username, role, can[]}
  GET  /api/state    -> the ledger, filtered for the caller's role
  PUT  /api/state    -> merges the caller's permitted changes
  GET  /api/users    -> superadmin only; POST adds, DELETE removes
  GET  /api/health

ACCESS CONTROL
--------------
Authentication is in backend/auth.py; what each role may see and change is in
backend/roles.py. Both are enforced here, server-side. The browser is told what
to hide only as a convenience -- the payload itself is filtered, because
anything sent to a browser can be read out of it.

Request-level hardening (Host validation against DNS rebinding, body-size cap,
security headers) is in backend/security.py. Read the security section of
README.md before binding to anything other than localhost.
"""

import json
import threading
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles

from . import auth, db, roles, security

# The repo root: index.html and its assets live one level up from backend/.
SITE_ROOT = Path(__file__).resolve().parent.parent

# Shared by the create-user and change-password endpoints so the two
# cannot drift apart.
MIN_PASSWORD_LENGTH = 8


# Guards the read-modify-write in put_state.
SAVE_LOCK = threading.Lock()


@asynccontextmanager
async def lifespan(app: FastAPI):
    db.init_db()
    auth.init_auth_schema()
    auth.purge_expired_sessions()
    generated = auth.ensure_superadmin()
    if generated:
        banner = "=" * 68
        print("", flush=True)
        print(banner, flush=True)
        print("  Superadmin account created (shown once - only its hash is stored)", flush=True)
        print("", flush=True)
        print("      username:  superadmin", flush=True)
        print("      password:  %s" % generated, flush=True)
        print("", flush=True)
        print("  Sign in, then reset it later with:", flush=True)
        print("      py -m backend.manage passwd superadmin", flush=True)
        print(banner, flush=True)
        print("", flush=True)
    yield


app = FastAPI(
    title="Lextria IP Ledger",
    description="Local backend for the Lextria trademark / copyright / design ledger.",
    version="2.0.0",
    lifespan=lifespan,
    # No interactive docs. On an unauthenticated API, Swagger UI is a ready-made
    # "Try it out" button wired to PUT /api/state — it hands a stranger who finds
    # the port a one-click way to overwrite the ledger, and publishes the exact
    # request shape to do it with. The endpoints are documented in README.md.
    docs_url=None,
    redoc_url=None,
    openapi_url=None,
)


@app.middleware("http")
async def harden(request: Request, call_next):
    """Host validation, body cap and security headers, on every request."""
    # 1. Reject anything addressed to a domain name. See security.host_is_safe:
    #    this is what stops a malicious page from reaching a localhost-bound
    #    server via DNS rebinding.
    if not security.host_is_safe(request.headers.get("host", "")):
        return PlainTextResponse(
            "Host not allowed. Reach this server as localhost or by IP address.",
            status_code=421,  # Misdirected Request
        )

    # 2. Reject an oversized body before it is read into memory. This is the
    #    cheap fast path via Content-Length; put_state independently enforces
    #    the same cap while streaming, for a chunked request that declares none.
    length = request.headers.get("content-length")
    if length and length.isdigit() and int(length) > security.MAX_BODY_BYTES:
        return JSONResponse(
            status_code=413,
            content={"error": f"Ledger too large (limit {security.MAX_BODY_BYTES} bytes)."},
        )

    response = await call_next(request)
    for header, value in security.SECURITY_HEADERS.items():
        response.headers.setdefault(header, value)
    return response


@app.get("/api/health")
def health():
    return {"status": "ok"}


def current_user(request: Request):
    """The signed-in user for this request, or None."""
    return auth.session_user(request.cookies.get(auth.SESSION_COOKIE))


def _unauthenticated():
    return JSONResponse(
        status_code=401,
        content={"error": "Sign in required.", "authRequired": True},
    )



async def json_object(request: Request):
    """Parse a JSON object body, or return (None, error_response).

    `await request.json()` raises on malformed input, which without this became
    an unhandled 500 on unauthenticated endpoints -- anyone could crash a
    request handler with four bytes of garbage.
    """
    try:
        payload = json.loads(await request.body())
    except (json.JSONDecodeError, UnicodeDecodeError):
        return None, JSONResponse(status_code=400,
                                  content={"error": "Malformed JSON in request body."})
    if not isinstance(payload, dict):
        return None, JSONResponse(status_code=400,
                                  content={"error": "Request body must be a JSON object."})
    return payload, None


def _cookie_is_secure(request: Request) -> bool:
    """Mark the session cookie Secure only when the connection can carry it.

    Setting it unconditionally would break plain-HTTP localhost, where the
    browser would refuse to store the cookie and no one could sign in.
    """
    if request.url.scheme == "https":
        return True
    # Behind a TLS-terminating reverse proxy the hop to us is plain HTTP.
    return request.headers.get("x-forwarded-proto", "").split(",")[0].strip() == "https"


def _client_ip(request: Request) -> str:
    """Best-effort source address, for throttling and the login history.

    Behind a reverse proxy the direct TCP peer is the proxy itself, not the
    real client, so X-Forwarded-For (its first, left-most entry -- the
    original client) is preferred when present. This is only ever used for
    rate-limiting and an audit trail, never for access control, so a spoofed
    header at worst pollutes those, rather than granting anything.
    """
    forwarded = request.headers.get("x-forwarded-for", "")
    if forwarded:
        first = forwarded.split(",")[0].strip()
        if first:
            return first
    return request.client.host if request.client else "unknown"


@app.post("/api/login")
async def login(request: Request):
    payload, error = await json_object(request)
    if error:
        return error

    username = payload.get("username")
    ip = _client_ip(request)

    # A pure request-volume cap, ahead of anything else: no single account has
    # to reach MAX_FAILURES for this to bite, so it also covers one address
    # spraying a common password across many different usernames. In-memory
    # only (see auth.ip_login_wait_seconds) -- nothing to migrate, nothing
    # written to disk on every attempt.
    ip_wait = auth.ip_login_wait_seconds(ip)
    if ip_wait:
        return JSONResponse(status_code=429, content={
            "error": "Too many sign-in requests from this address. Try again in %d minute(s)."
                     % max(1, round(ip_wait / 60)),
        })

    user, locked_for = auth.authenticate_throttled(username, payload.get("password"))
    auth.record_login_event(username, success=user is not None, ip=ip)

    if user is None:
        if locked_for:
            return JSONResponse(status_code=429, content={
                "error": "Too many failed attempts. Try again in %d minute(s)."
                         % max(1, round(locked_for / 60)),
            })
        # One message for both a wrong name and a wrong password, so the form
        # cannot be used to discover which usernames exist.
        return JSONResponse(status_code=401,
                            content={"error": "Incorrect username or password."})

    token = auth.start_session(user["id"])
    response = JSONResponse({
        "ok": True,
        "user": {"username": user["username"], "role": user["role"],
                 "roleLabel": roles.ROLE_LABELS.get(user["role"], user["role"]),
                 "can": roles.capabilities(user["role"])},
    })
    response.set_cookie(
        auth.SESSION_COOKIE, token,
        httponly=True,      # unreadable from JavaScript, so XSS cannot steal it
        samesite="strict",  # not sent on cross-site requests, which blocks CSRF
        secure=_cookie_is_secure(request),
        max_age=auth.SESSION_HOURS * 3600,
        path="/",
    )
    return response


@app.get("/api/login-history")
def login_history(request: Request):
    """Recent sign-in attempts (success and failure), super admin only.

    The lockout in /api/login stops a brute-force run from succeeding; this is
    what lets a super admin actually SEE that one was attempted, rather than
    only ever feeling it as "I got locked out" with no visibility into why.
    """
    user = current_user(request)
    if user is None:
        return _unauthenticated()
    if not roles.can(user["role"], "manage_users"):
        return JSONResponse(status_code=403, content={"error": "Not permitted."})
    return {"events": auth.recent_login_events(200)}


@app.post("/api/sessions/revoke-others")
def revoke_other_sessions(request: Request):
    """Sign this account out on every OTHER device, keeping this one signed in.

    Lighter than a password change (which also ends this session): for
    "I think I left myself logged in somewhere," not "my password may be
    known to someone else."
    """
    user = current_user(request)
    if user is None:
        return _unauthenticated()
    token = request.cookies.get(auth.SESSION_COOKIE)
    auth.end_other_sessions(user["id"], token)
    return {"ok": True}


@app.post("/api/logout")
async def logout(request: Request):
    auth.end_session(request.cookies.get(auth.SESSION_COOKIE))
    response = JSONResponse({"ok": True})
    response.delete_cookie(auth.SESSION_COOKIE, path="/")
    return response


@app.get("/api/me")
def me(request: Request):
    user = current_user(request)
    if user is None:
        return {"signedIn": False}
    return {
        "signedIn": True,
        "username": user["username"],
        "role": user["role"],
        "roleLabel": roles.ROLE_LABELS.get(user["role"], user["role"]),
        "can": roles.capabilities(user["role"]),
    }


@app.get("/api/users")
def get_users(request: Request):
    user = current_user(request)
    if user is None:
        return _unauthenticated()
    if not roles.can(user["role"], "manage_users"):
        return JSONResponse(status_code=403, content={"error": "Not permitted."})
    return {"users": auth.list_users(), "roles": [
        {"value": r, "label": roles.ROLE_LABELS[r]} for r in roles.ALL_ROLES]}


@app.post("/api/users")
async def add_user(request: Request):
    user = current_user(request)
    if user is None:
        return _unauthenticated()
    if not roles.can(user["role"], "manage_users"):
        return JSONResponse(status_code=403, content={"error": "Not permitted."})

    payload, error = await json_object(request)
    if error:
        return error
    username = (payload.get("username") or "").strip()
    password = payload.get("password") or ""
    role = payload.get("role")
    if not username or not password:
        return JSONResponse(status_code=400,
                            content={"error": "Username and password are required."})
    if len(password) < MIN_PASSWORD_LENGTH:
        return JSONResponse(status_code=400, content={
            "error": "Password must be at least %d characters." % MIN_PASSWORD_LENGTH})
    weak_reason = auth.is_weak_password(password, username)
    if weak_reason:
        return JSONResponse(status_code=400, content={"error": weak_reason})
    if role not in roles.ALL_ROLES:
        return JSONResponse(status_code=400, content={"error": "Unknown role."})

    if auth.create_user(username, password, role) is None:
        return JSONResponse(status_code=409,
                            content={"error": "That username is already taken."})
    return {"ok": True}


def _clear_stale_assignments():
    """Drop any matter's assignedTo that no longer names a real, active
    account, right when an account stops being one -- rather than leaving
    those matters invisible to every drafter until some unrelated save
    happens to trigger roles.validate_assignments (see put_state)."""
    with SAVE_LOCK:
        stored = db.load_state()
        if not isinstance(stored, dict):
            return
        active_usernames = [u["username"] for u in auth.list_users() if u["active"]]
        if roles.validate_assignments(stored, active_usernames):
            db.save_state(stored)


@app.delete("/api/users/{user_id}")
def remove_user(user_id: int, request: Request):
    user = current_user(request)
    if user is None:
        return _unauthenticated()
    if not roles.can(user["role"], "manage_users"):
        return JSONResponse(status_code=403, content={"error": "Not permitted."})
    if user_id == user["id"]:
        return JSONResponse(status_code=400,
                            content={"error": "You cannot delete your own account."})
    if not auth.delete_user(user_id):
        return JSONResponse(status_code=404, content={"error": "No such user."})
    _clear_stale_assignments()
    return {"ok": True}


@app.patch("/api/users/{user_id}")
async def update_user(user_id: int, request: Request):
    """Suspend or restore an account, or change its role."""
    user = current_user(request)
    if user is None:
        return _unauthenticated()
    if not roles.can(user["role"], "manage_users"):
        return JSONResponse(status_code=403, content={"error": "Not permitted."})

    payload, error = await json_object(request)
    if error:
        return error

    if user_id == user["id"]:
        # Suspending or demoting yourself is how an installation ends up with
        # nobody able to manage users.
        return JSONResponse(status_code=400,
                            content={"error": "You cannot change your own account here."})

    if "active" in payload:
        if not auth.set_active(user_id, bool(payload["active"])):
            return JSONResponse(status_code=404, content={"error": "No such user."})
    if "role" in payload:
        if payload["role"] not in roles.ALL_ROLES:
            return JSONResponse(status_code=400, content={"error": "Unknown role."})
        if not auth.set_role(user_id, payload["role"]):
            return JSONResponse(status_code=404, content={"error": "No such user."})
    if payload.get("active") is False:
        _clear_stale_assignments()
    return {"ok": True}


@app.post("/api/password")
async def change_own_password(request: Request):
    """Change your own password. Requires the current one."""
    user = current_user(request)
    if user is None:
        return _unauthenticated()

    payload, error = await json_object(request)
    if error:
        return error

    current = payload.get("currentPassword") or ""
    new = payload.get("newPassword") or ""
    if len(new) < MIN_PASSWORD_LENGTH:
        return JSONResponse(status_code=400, content={
            "error": "New password must be at least %d characters." % MIN_PASSWORD_LENGTH})
    weak_reason = auth.is_weak_password(new, user["username"])
    if weak_reason:
        return JSONResponse(status_code=400, content={"error": weak_reason})
    if auth.authenticate(user["username"], current) is None:
        return JSONResponse(status_code=403,
                            content={"error": "Your current password is not correct."})

    auth.set_password(user["username"], new)
    # set_password signs every session out, including this one, so issue a
    # fresh cookie rather than logging the user out of the tab they are in.
    token = auth.start_session(user["id"])
    response = JSONResponse({"ok": True})
    response.set_cookie(
        auth.SESSION_COOKIE, token, httponly=True, samesite="strict",
        secure=_cookie_is_secure(request),
        max_age=auth.SESSION_HOURS * 3600, path="/",
    )
    return response


@app.get("/api/assignees")
def assignees(request: Request):
    """Usernames a matter can be assigned to.

    Available to anyone who may edit a matter, not just a superadmin: a
    trademark admin has to be able to assign work without being able to manage
    accounts. Only names and roles are returned, never anything else about the
    account.
    """
    user = current_user(request)
    if user is None:
        return _unauthenticated()
    if not roles.can(user["role"], "edit_matter"):
        return JSONResponse(status_code=403, content={"error": "Not permitted."})
    return {"assignees": [
        {"username": u["username"], "role": u["role"],
         "roleLabel": roles.ROLE_LABELS.get(u["role"], u["role"])}
        for u in auth.list_users() if u["active"]
    ]}


@app.get("/api/state")
def get_state(request: Request):
    """Return the ledger as this user's role is allowed to see it.

    Financial fields are stripped from the payload here, not merely hidden in
    the UI — anything sent to the browser is readable from dev tools.

    `revision` identifies exactly which version of the document this is. The
    client echoes it back on its next PUT (as the X-Ledger-Revision header) so
    the server can tell a deliberate edit apart from one based on stale data —
    see roles.merge_for_role and the "baseline" it is given in put_state below.
    """
    user = current_user(request)
    if user is None:
        return {"configured": True, "authorized": False,
                "authRequired": True, "state": None}

    document, revision = db.load_state_with_revision()
    return {
        "configured": True,
        "authorized": True,
        "authRequired": True,
        "user": {"username": user["username"], "role": user["role"],
                 "roleLabel": roles.ROLE_LABELS.get(user["role"], user["role"]),
                 "can": roles.capabilities(user["role"])},
        "revision": revision,
        "state": roles.redact_for_role(document, user["role"], user["username"]),
    }


@app.put("/api/state")
async def put_state(request: Request):
    """Apply this user's permitted changes to the ledger.

    Never a blind replace for a restricted role: the payload is merged onto the
    stored document by roles.merge_for_role, so a client that was given a
    filtered ledger cannot delete what it could not see, and one that was given
    no financial values cannot blank them.
    """
    user = current_user(request)
    if user is None:
        return _unauthenticated()
    # Read the body in chunks and stop at the cap, rather than `await
    # request.body()`, which would buffer the whole payload first. A request
    # using chunked transfer-encoding carries no Content-Length for the
    # middleware to check, so this is the enforcement that actually binds.
    chunks = []
    received = 0
    async for chunk in request.stream():
        received += len(chunk)
        if received > security.MAX_BODY_BYTES:
            return JSONResponse(
                status_code=413,
                content={"error": f"Ledger too large (limit {security.MAX_BODY_BYTES} bytes)."},
            )
        chunks.append(chunk)

    try:
        document = json.loads(b"".join(chunks))
    except (json.JSONDecodeError, UnicodeDecodeError):
        return JSONResponse(
            status_code=400,
            content={"error": "Malformed JSON in request body."},
        )

    if not isinstance(document, dict):
        return JSONResponse(
            status_code=400,
            content={"error": "Request body must be a JSON object (the full ledger state)."},
        )

    # What did this browser last actually load? Looking that up (rather than
    # trusting the incoming document to represent it) is what lets the merge
    # tell "I am deliberately changing this" apart from "my copy just predates
    # someone else's edit" -- see roles.merge_for_role for how each case is
    # handled. Absent or unparseable means "unknown", which every branch of
    # the merge has an explicit, documented fallback for.
    client_revision = None
    header_value = request.headers.get("x-ledger-revision")
    if header_value is not None:
        try:
            client_revision = int(header_value)
        except ValueError:
            client_revision = None

    # Serialise read-modify-write: two saves landing together would otherwise
    # each merge onto the same stored document and the later would drop the
    # earlier one's changes.
    with SAVE_LOCK:
        stored = db.load_state()
        baseline = db.get_document_at_revision(client_revision) if client_revision else None
        try:
            to_store, id_remap = roles.merge_for_role(
                stored, document, user["role"], user["username"], baseline=baseline)
        except Exception:
            return JSONResponse(
                status_code=400,
                content={"error": "Could not apply those changes."},
            )

        # A matter assigned to a name that is not a real, active account is
        # invisible to every drafter with no warning anywhere else in the app
        # -- clear it here rather than let that happen silently.
        active_usernames = [u["username"] for u in auth.list_users() if u["active"]]
        cleared_assignments = roles.validate_assignments(to_store, active_usernames)

        try:
            revision = db.save_state(to_store)
        except Exception:
            return JSONResponse(
                status_code=500,
                content={"error": "Could not save to the ledger database."},
            )

    response = {"ok": True, "revision": revision}
    if id_remap["records"] or id_remap["clients"]:
        response["idRemap"] = id_remap
    if cleared_assignments:
        response["clearedAssignments"] = cleared_assignments
    return response


@app.get("/")
def index():
    """Serve the single-page app's HTML shell."""
    return FileResponse(SITE_ROOT / "index.html", media_type="text/html")


# The front end's CSS, JS and logo. Mounted on the dedicated static/ directory,
# never on SITE_ROOT — a mount on "/" would also publish backend/lextria.db and
# .git/ to anyone who can reach the port. Anything the page needs goes in
# static/; nothing outside it is reachable over HTTP.
app.mount("/static", StaticFiles(directory=SITE_ROOT / "static"), name="static")
