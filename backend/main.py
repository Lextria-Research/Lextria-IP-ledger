"""FastAPI backend for the Lextria IP Ledger.

There is no environment configuration of any kind: accounts, sessions and the
ledger all live in one SQLite file next to this module.

Authentication is by per-account ACCESS KEY only -- there are no passwords. A
key is accepted either by trading it for an HttpOnly session cookie (what the
browser does) or on every request as `Authorization: Bearer <key>` or
`X-Lextria-Key: <key>` (what a script does). See backend/auth.py.

  POST   /api/login                   {key} -> sets an HttpOnly session cookie
  POST   /api/logout
  GET    /api/me                      -> {signedIn, username, role, can[]}
  GET    /api/state                   -> the ledger, filtered for the caller
  PUT    /api/state                   -> merges the caller's permitted changes
  POST   /api/key/rotate              -> replace your own key (returned once)
  GET    /api/users                   -> superadmin only; POST adds (returns the
                                         new key once), PATCH updates, DELETE
                                         removes, POST .../rotate-key reissues
  GET    /api/assignees               -> names a matter may be assigned to
  GET    /api/login-history           -> superadmin only
  POST   /api/sessions/revoke-others
  GET    /api/health

ACCESS CONTROL
--------------
Authentication is in backend/auth.py; what each role may see and change is in
backend/roles.py. Both are enforced here, server-side. The browser is told what
to hide only as a convenience -- the payload itself is filtered, because
anything sent to a browser can be read out of it.

Request-level hardening (Host validation against DNS rebinding, body-size cap,
security headers, the CSP nonce) is in backend/security.py. Read the security
section of README.md before binding to anything other than localhost.
"""

import json
import re
import threading
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse, PlainTextResponse

from . import auth, db, roles, security

# The repo root: index.html lives one level up from backend/.
SITE_ROOT = Path(__file__).resolve().parent.parent
INDEX_HTML = SITE_ROOT / "index.html"

# Guards the read-modify-write in put_state.
SAVE_LOCK = threading.Lock()

# The attribute the CSP nonce is stamped onto. index.html carries exactly one
# executable <script>, tagged with this id so the substitution below can find it
# without parsing HTML.
APP_SCRIPT_TAG = '<script id="app-script">'


@asynccontextmanager
async def lifespan(app: FastAPI):
    db.init_db()
    auth.init_auth_schema()
    auth.purge_expired_sessions()
    generated = auth.ensure_superadmin()
    if generated:
        banner = "=" * 72
        print("", flush=True)
        print(banner, flush=True)
        print("  Superadmin account created (key shown once - only its hash is stored)",
              flush=True)
        print("", flush=True)
        print("      username:  superadmin", flush=True)
        print("      key:       %s" % generated, flush=True)
        print("", flush=True)
        print("  Sign in with that key. If it is lost, issue a new one with:", flush=True)
        print("      py -m backend.manage rotate superadmin", flush=True)
        print(banner, flush=True)
        print("", flush=True)
    yield


app = FastAPI(
    title="Lextria IP Ledger",
    description="Backend for the Lextria trademark / copyright / design ledger.",
    version="3.0.0",
    lifespan=lifespan,
    # No interactive docs. Swagger UI is a ready-made "Try it out" button wired
    # to PUT /api/state -- it publishes the exact request shape for overwriting
    # the ledger to anyone who finds the port. The endpoints are documented in
    # README.md instead.
    docs_url=None,
    redoc_url=None,
    openapi_url=None,
)


@app.middleware("http")
async def harden(request: Request, call_next):
    """Host validation, body cap, CSP nonce and security headers."""
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
            content={"error": "Ledger too large (limit %d bytes)."
                              % security.MAX_BODY_BYTES},
        )

    # 3. Mint this response's script nonce before the handler runs, so the
    #    handler that renders index.html can stamp the same value into the page
    #    that the header will advertise.
    nonce = security.new_nonce()
    request.state.csp_nonce = nonce

    response = await call_next(request)
    response.headers.setdefault("Content-Security-Policy",
                                security.content_security_policy(nonce))
    for header, value in security.SECURITY_HEADERS.items():
        response.headers.setdefault(header, value)
    return response


@app.get("/api/health")
def health():
    return {"status": "ok"}


def _presented_key(request: Request):
    """The access key sent on this request's headers, or None."""
    custom = request.headers.get("x-lextria-key")
    if custom:
        return custom.strip()
    header = request.headers.get("authorization", "")
    match = re.match(r"^\s*Bearer\s+(\S+)\s*$", header, re.I)
    return match.group(1) if match else None


def _resolve_caller(request: Request):
    """(user, error_response) for this request.

    A key on the headers takes precedence over a session cookie, and a WRONG key
    is an error in its own right -- it is never quietly ignored in favour of a
    cookie that happens to be present, because a script that believes it is
    acting as one account must not silently act as another.
    """
    key = _presented_key(request)
    if key is not None:
        ip = _client_ip(request)
        wait = auth.ip_wait_seconds(ip)
        if wait:
            return None, _too_many(wait)
        user = auth.authenticate_key(key)
        if user is None:
            auth.record_ip_attempt(ip)
            return None, JSONResponse(status_code=401, content={
                "error": "That access key is not valid.", "authRequired": True})
        return user, None
    return auth.session_user(request.cookies.get(auth.SESSION_COOKIE)), None


def current_user(request: Request):
    """The signed-in user for this request, or None (errors folded into None)."""
    user, _error = _resolve_caller(request)
    return user


def _unauthenticated():
    return JSONResponse(
        status_code=401,
        content={"error": "Sign in with your access key.", "authRequired": True},
    )


def _forbidden():
    return JSONResponse(status_code=403, content={"error": "Not permitted."})


def _too_many(wait_seconds):
    return JSONResponse(status_code=429, content={
        "error": "Too many attempts from this address. Try again in %d minute(s)."
                 % max(1, round(wait_seconds / 60)),
    })


def _require(request: Request, capability):
    """(user, None) if the caller may do this, else (None, error_response)."""
    user, error = _resolve_caller(request)
    if error:
        return None, error
    if user is None:
        return None, _unauthenticated()
    if capability and not roles.can(user["role"], capability):
        return None, _forbidden()
    return user, None


async def json_object(request: Request):
    """Parse a JSON object body, or return (None, error_response).

    Parsing raises on malformed input, which without this becomes an unhandled
    500 on unauthenticated endpoints -- anyone could crash a request handler
    with four bytes of garbage.
    """
    try:
        payload = json.loads(await request.body())
    except (json.JSONDecodeError, UnicodeDecodeError):
        return None, JSONResponse(
            status_code=400, content={"error": "Malformed JSON in request body."})
    if not isinstance(payload, dict):
        return None, JSONResponse(
            status_code=400, content={"error": "Request body must be a JSON object."})
    return payload, None


def _cookie_is_secure(request: Request):
    """Mark the session cookie Secure only when the connection can carry it.

    Setting it unconditionally would break plain-HTTP localhost, where the
    browser would refuse to store the cookie and no one could sign in.
    """
    if request.url.scheme == "https":
        return True
    # Behind a TLS-terminating reverse proxy the hop to us is plain HTTP.
    return request.headers.get("x-forwarded-proto", "").split(",")[0].strip() == "https"


def _set_session_cookie(response, token, request: Request):
    response.set_cookie(
        auth.SESSION_COOKIE, token,
        httponly=True,      # unreadable from JavaScript, so XSS cannot steal it
        samesite="strict",  # not sent on cross-site requests, which blocks CSRF
        secure=_cookie_is_secure(request),
        max_age=auth.SESSION_HOURS * 3600,
        path="/",
    )
    return response


def _client_ip(request: Request):
    """Best-effort source address, for throttling and the login history.

    Behind a reverse proxy the direct TCP peer is the proxy itself, not the real
    client, so X-Forwarded-For (its first, left-most entry -- the original
    client) is preferred when present. This is only ever used for rate-limiting
    and an audit trail, never for access control, so a spoofed header at worst
    pollutes those rather than granting anything.
    """
    forwarded = request.headers.get("x-forwarded-for", "")
    if forwarded:
        first = forwarded.split(",")[0].strip()
        if first:
            return first
    return request.client.host if request.client else "unknown"


def _identity(user):
    """The caller's own account, as the front end needs to render itself."""
    return {
        "username": user["username"],
        "role": user["role"],
        "roleLabel": roles.ROLE_LABELS.get(user["role"], user["role"]),
        "can": roles.capabilities(user["role"]),
    }


# --- Authentication ---------------------------------------------------------

@app.post("/api/login")
async def login(request: Request):
    """Trade an access key for a session cookie.

    The browser does this once rather than holding the key and sending it on
    every request: a key in page storage is readable by any script that gets
    onto the page, while an HttpOnly cookie is not.
    """
    payload, error = await json_object(request)
    if error:
        return error

    ip = _client_ip(request)
    wait = auth.ip_wait_seconds(ip)
    if wait:
        return _too_many(wait)
    # Every sign-in attempt counts, successful or not, so one address cannot
    # cycle through keys at speed.
    auth.record_ip_attempt(ip)

    user = auth.authenticate_key((payload.get("key") or "").strip())
    auth.record_login_event(user["username"] if user else None,
                            success=user is not None, ip=ip)
    if user is None:
        # Deliberately the same for an unknown key and a suspended account's
        # key: neither should reveal that the other exists.
        return JSONResponse(status_code=401,
                            content={"error": "That access key is not valid."})

    token = auth.start_session(user["id"])
    return _set_session_cookie(
        JSONResponse({"ok": True, "user": _identity(user)}), token, request)


@app.post("/api/logout")
async def logout(request: Request):
    auth.end_session(request.cookies.get(auth.SESSION_COOKIE))
    response = JSONResponse({"ok": True})
    response.delete_cookie(auth.SESSION_COOKIE, path="/")
    return response


@app.get("/api/me")
def me(request: Request):
    user, error = _resolve_caller(request)
    if error:
        return error
    if user is None:
        return {"signedIn": False}
    identity = _identity(user)
    identity["signedIn"] = True
    return identity


@app.post("/api/key/rotate")
def rotate_own_key(request: Request):
    """Replace your own access key. The new key is in this response and nowhere
    else. Every existing session ends; if this request came from the browser, a
    fresh cookie is issued so the tab it came from stays signed in."""
    user, error = _require(request, None)
    if error:
        return error
    key = auth.rotate_key(user["id"])
    response = JSONResponse({"ok": True, "key": key})
    if _presented_key(request) is None:
        _set_session_cookie(response, auth.start_session(user["id"]), request)
    return response


@app.post("/api/sessions/revoke-others")
def revoke_other_sessions(request: Request):
    """Sign this account out on every OTHER device, keeping this one signed in.

    Lighter than rotating your key (which also ends this session): for "I think
    I left myself signed in somewhere," not "my key may be known to someone
    else" -- that case calls POST /api/key/rotate instead.
    """
    user, error = _require(request, None)
    if error:
        return error
    token = request.cookies.get(auth.SESSION_COOKIE)
    auth.end_other_sessions(user["id"], token)
    return {"ok": True}


@app.get("/api/login-history")
def login_history(request: Request):
    """Recent sign-in attempts, success and failure. Super admin only.

    The lockout in /api/login stops a brute-force run from succeeding; this is
    what lets a super admin actually SEE that one was attempted, rather than
    only ever feeling it as "I got locked out" with no visibility into why.
    """
    _user, error = _require(request, "manage_users")
    if error:
        return error
    return {"events": auth.recent_login_events(200)}


# --- User administration ----------------------------------------------------

@app.get("/api/users")
def get_users(request: Request):
    user, error = _require(request, "manage_users")
    if error:
        return error
    return {
        "users": auth.list_users(),
        "roles": [{"value": r, "label": roles.ROLE_LABELS[r]} for r in roles.ALL_ROLES],
        "you": user["id"],
    }


@app.post("/api/users")
async def add_user(request: Request):
    """Create an account. Its access key is in this response and nowhere else."""
    _user, error = _require(request, "manage_users")
    if error:
        return error

    payload, error = await json_object(request)
    if error:
        return error
    username = (payload.get("username") or "").strip()
    role = payload.get("role")

    if not username:
        return JSONResponse(status_code=400, content={"error": "A username is required."})
    if role not in roles.ALL_ROLES:
        return JSONResponse(status_code=400, content={"error": "Unknown role."})

    user_id, key = auth.create_user(username, role)
    if user_id is None:
        return JSONResponse(status_code=409,
                            content={"error": "That username is already taken."})
    return {"ok": True, "id": user_id, "username": username, "key": key}


def _clear_stale_assignments():
    """Drop any matter's assignedTo that no longer names a real, active account,
    right when an account stops being one -- rather than leaving those matters
    invisible to every drafter until some unrelated save happens to trigger
    roles.validate_assignments (see put_state)."""
    with SAVE_LOCK:
        stored = db.load_state()
        if not isinstance(stored, dict):
            return
        if roles.validate_assignments(stored, auth.active_usernames()):
            db.save_state(stored)


@app.patch("/api/users/{user_id}")
async def update_user(user_id: int, request: Request):
    """Suspend or restore an account, or change its role."""
    user, error = _require(request, "manage_users")
    if error:
        return error

    payload, error = await json_object(request)
    if error:
        return error

    if user_id == user["id"]:
        # Suspending or demoting yourself is how an installation ends up with
        # nobody able to manage users.
        return JSONResponse(status_code=400,
                            content={"error": "You cannot change your own account here."})

    # Either change would remove a superadmin from circulation, so both are
    # checked against the same "someone must be left" rule.
    removing_superadmin = (payload.get("active") is False
                           or ("role" in payload and payload["role"] != roles.SUPERADMIN))
    if removing_superadmin and auth.count_active_superadmins(excluding_id=user_id) == 0:
        target = auth.list_users()
        if any(u["id"] == user_id and u["role"] == roles.SUPERADMIN and u["active"]
               for u in target):
            return JSONResponse(status_code=400, content={
                "error": "This is the last active super admin. Promote another "
                         "account first, or nobody will be able to manage users "
                         "or see financial data.",
            })

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


@app.delete("/api/users/{user_id}")
def remove_user(user_id: int, request: Request):
    user, error = _require(request, "manage_users")
    if error:
        return error
    if user_id == user["id"]:
        return JSONResponse(status_code=400,
                            content={"error": "You cannot delete your own account."})
    if auth.count_active_superadmins(excluding_id=user_id) == 0:
        return JSONResponse(status_code=400, content={
            "error": "This is the last active super admin. Promote another "
                     "account first.",
        })
    if not auth.delete_user(user_id):
        return JSONResponse(status_code=404, content={"error": "No such user."})
    _clear_stale_assignments()
    return {"ok": True}


@app.post("/api/users/{user_id}/rotate-key")
def rotate_user_key(user_id: int, request: Request):
    """Issue a new key for an account (lost key, or a key that may have leaked).
    The old key and every session opened with it stop working immediately."""
    _user, error = _require(request, "manage_users")
    if error:
        return error
    key = auth.rotate_key(user_id)
    if key is None:
        return JSONResponse(status_code=404, content={"error": "No such user."})
    return {"ok": True, "key": key}


@app.get("/api/assignees")
def assignees(request: Request):
    """Usernames a matter can be assigned to.

    Available to anyone who may assign work, not just a superadmin: a trademark
    admin has to be able to hand a matter to a drafter without also being able
    to manage accounts. Only names and roles are returned, never anything else
    about the account.
    """
    _user, error = _require(request, "assign_matter")
    if error:
        return error
    return {"assignees": [
        {"username": u["username"], "role": u["role"],
         "roleLabel": roles.ROLE_LABELS.get(u["role"], u["role"])}
        for u in auth.list_users() if u["active"]
    ]}


# --- The ledger -------------------------------------------------------------

@app.get("/api/state")
def get_state(request: Request):
    """Return the ledger as this user's role is allowed to see it.

    Financial fields are stripped from the payload here, not merely hidden in
    the UI -- anything sent to the browser is readable from dev tools.

    `revision` identifies exactly which version of the document this is. The
    client echoes it back on its next PUT (as the X-Ledger-Revision header) so
    the server can tell a deliberate edit apart from one based on stale data --
    see roles.merge_for_role and the "baseline" it is given in put_state below.
    """
    user, error = _resolve_caller(request)
    if error:
        return error
    if user is None:
        return {"configured": True, "authorized": False,
                "authRequired": True, "state": None}

    document, revision = db.load_state_with_revision()
    return {
        "configured": True,
        "authorized": True,
        "authRequired": True,
        "user": _identity(user),
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
    user, error = _require(request, None)
    if error:
        return error

    # Read the body in chunks and stop at the cap, rather than buffering the
    # whole payload first. A request using chunked transfer-encoding carries no
    # Content-Length for the middleware to check, so this is the enforcement
    # that actually binds.
    chunks = []
    received = 0
    async for chunk in request.stream():
        received += len(chunk)
        if received > security.MAX_BODY_BYTES:
            return JSONResponse(
                status_code=413,
                content={"error": "Ledger too large (limit %d bytes)."
                                  % security.MAX_BODY_BYTES},
            )
        chunks.append(chunk)

    try:
        document = json.loads(b"".join(chunks))
    except (json.JSONDecodeError, UnicodeDecodeError):
        return JSONResponse(status_code=400,
                            content={"error": "Malformed JSON in request body."})

    if not isinstance(document, dict):
        return JSONResponse(status_code=400, content={
            "error": "Request body must be a JSON object (the full ledger state)."})

    # What did this browser last actually load? Looking that up (rather than
    # trusting the incoming document to represent it) is what lets the merge
    # tell "I am deliberately changing this" apart from "my copy just predates
    # someone else's edit" -- see roles.merge_for_role for how each case is
    # handled. Absent or unparseable means "unknown", which every branch of the
    # merge has an explicit, documented fallback for.
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
            return JSONResponse(status_code=400,
                                content={"error": "Could not apply those changes."})

        # A matter assigned to a name that is not a real, active account is
        # invisible to every drafter with no warning anywhere else in the app --
        # clear it here rather than let that happen silently.
        cleared_assignments = roles.validate_assignments(
            to_store, auth.active_usernames())

        try:
            revision = db.save_state(to_store)
        except Exception:
            return JSONResponse(status_code=500,
                                content={"error": "Could not save to the ledger database."})

    response = {"ok": True, "revision": revision}
    if id_remap["records"] or id_remap["clients"]:
        response["idRemap"] = id_remap
    if cleared_assignments:
        response["clearedAssignments"] = cleared_assignments
    return response


# --- The page ---------------------------------------------------------------

@app.get("/")
def index(request: Request):
    """Serve the single-page app, stamped with this response's CSP nonce.

    Read fresh on every request rather than cached at import: the page is a
    single file a person edits directly, and serving a stale copy from memory
    after an edit is a confusing way to lose an afternoon. It is one file read
    on a request that is already doing far more work than that.
    """
    try:
        html = INDEX_HTML.read_text(encoding="utf-8")
    except OSError:
        return PlainTextResponse("index.html is missing from the repository root.",
                                 status_code=500)

    nonce = getattr(request.state, "csp_nonce", "")
    html = html.replace(
        APP_SCRIPT_TAG,
        '<script id="app-script" nonce="%s">' % nonce,
        1,
    )
    return HTMLResponse(html)
