"""Request-level hardening for the Lextria IP Ledger backend.

Everything here sits in front of authentication rather than replacing it: these
are the measures that keep a remote attacker from reaching a server the
operator believed was private, and that limit the damage a signed-in but
hostile client can do.
"""

import ipaddress
import secrets

# Largest ledger document accepted on PUT /api/state.
#
# The client posts the whole ledger on every save, so this has to be generous --
# but unbounded is not an option: the body is buffered before anything can
# validate it, and each accepted save is written to disk and archived into
# ledger_history. Without a cap, one request can exhaust memory and grow the
# database without limit. A real ledger of a few thousand matters is comfortably
# under a megabyte; matter logos are stored as URLs, not embedded bytes.
MAX_BODY_BYTES = 8 * 1024 * 1024  # 8 MB


def host_is_safe(host_header):
    """Whether a Host header may be served. Blocks DNS rebinding.

    Binding to localhost does NOT, by itself, keep a browser-based attacker out.
    In a DNS-rebinding attack a page on evil.example.com re-resolves its own
    domain to 127.0.0.1; the victim's browser then issues same-origin requests
    to this server -- reading and overwriting the ledger -- and, crucially,
    sends `Host: evil.example.com` while doing it.

    Legitimate clients reach this server as `localhost` or by bare IP, never via
    a registered domain name. Accepting only those two forms breaks the attack
    at its one observable tell, and costs nothing: `localhost:8000` and
    `192.168.1.20:8000` both still work.

    A caller wanting a real hostname (behind a reverse proxy, say) should
    terminate at the proxy and let it own access control -- see README.
    """
    if not host_header:
        # HTTP/1.1 requires Host. Its absence is not a real browser.
        return False

    host = host_header.strip()

    # Bracketed IPv6 literal, optionally with a port: [::1] or [::1]:8000
    if host.startswith("["):
        end = host.find("]")
        if end == -1:
            return False
        host = host[1:end]
    else:
        # Strip a trailing :port. A bare IPv6 address has several colons and no
        # port, so only strip when exactly one colon is present.
        if host.count(":") == 1:
            host = host.rsplit(":", 1)[0]

    host = host.lower().rstrip(".")

    if host == "localhost":
        return True

    try:
        ipaddress.ip_address(host)
    except ValueError:
        # A registered domain name -- the signature of a rebinding attempt.
        return False
    return True


def new_nonce():
    """A fresh CSP nonce for one response."""
    return secrets.token_urlsafe(16)


def content_security_policy(nonce):
    """The CSP for one response, bound to that response's script nonce.

    The dashboard ships as a single self-contained index.html, so its
    application code is one inline <script> block. Allowing that with
    'unsafe-inline' would also allow any OTHER inline script -- including one an
    injection managed to get into the page -- which is precisely the class of
    bug CSP exists to stop. A nonce allows exactly the one block the server
    itself stamped on the way out, and nothing else: an injected <script> has no
    way to guess the value, which is freshly generated per response.

    Browsers ignore 'unsafe-inline' entirely when a nonce is present, so there
    is no need to list it as a fallback for older clients -- any browser too old
    to understand nonces is also too old to be running this app.

    style-src still needs 'unsafe-inline' because the UI sets style="" attributes
    as it builds HTML, and img-src needs https: because matter logos are
    arbitrary user-supplied URLs.
    """
    return "; ".join([
        "default-src 'self'",
        "script-src 'self' 'nonce-%s'" % nonce,
        "style-src 'self' 'unsafe-inline'",
        "font-src 'self'",
        "img-src 'self' data: https:",
        "connect-src 'self'",
        "form-action 'none'",
        "frame-ancestors 'none'",
        "base-uri 'none'",
        "object-src 'none'",
    ])


# Sent on every response, alongside the per-response CSP above.
SECURITY_HEADERS = {
    # Stop a stored value being sniffed into an executable type.
    "X-Content-Type-Options": "nosniff",
    # Belt-and-braces with frame-ancestors, for anything not reading CSP.
    "X-Frame-Options": "DENY",
    # Client matter names must not leak to third parties via Referer.
    "Referrer-Policy": "no-referrer",
    # This is private client data; never let a shared cache hold it.
    "Cache-Control": "no-store",
    # The dashboard uses none of these browser capabilities; refusing them
    # outright means an XSS that got past the CSP still cannot turn the page
    # into a camera/microphone/location snoop.
    "Permissions-Policy": ("geolocation=(), camera=(), microphone=(), "
                           "usb=(), payment=(), interest-cohort=()"),
    # Isolates this page's browsing context group from anything that opens or is
    # opened by it, closing off a class of cross-window timing/reference attacks.
    "Cross-Origin-Opener-Policy": "same-origin",
    # Nothing here is meant to be embedded or fetched by another origin; there is
    # no CORS configuration at all, and this says so explicitly rather than
    # relying on that omission alone.
    "Cross-Origin-Resource-Policy": "same-origin",
    # Legacy Flash/PDF cross-domain policy files are not used; refuse them.
    "X-Permitted-Cross-Domain-Policies": "none",
    # Ignored by every browser unless the response actually arrived over HTTPS
    # (RFC 6797), so this is inert on the plain-HTTP localhost default and takes
    # effect automatically the moment TLS is put in front of this server.
    "Strict-Transport-Security": "max-age=31536000; includeSubDomains",
}
