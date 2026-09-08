"""Request-level hardening for the Lextria IP Ledger backend.

The API is unauthenticated by design (there is no environment configuration and
no access key), so its safety rests entirely on *who can reach the port*. That
assumption is worth surprisingly little on its own, and this module supplies the
pieces that make it hold.

Nothing here is a substitute for authentication. It closes the gaps that would
let a remote attacker reach a server the operator believed was private.
"""

import ipaddress

# Largest ledger document accepted on PUT /api/state.
#
# The client posts the whole ledger on every save, so this has to be generous —
# but unbounded is not an option: `await request.body()` buffers the entire
# payload in memory before anything validates it, and each accepted save is
# written to disk and archived into ledger_history. Without a cap, one request
# can exhaust memory and grow the database without limit. A real ledger of a few
# thousand matters is comfortably under a megabyte; matter logos are stored as
# URLs, not embedded bytes.
MAX_BODY_BYTES = 8 * 1024 * 1024  # 8 MB


def host_is_safe(host_header: str) -> bool:
    """Whether a Host header may be served. Blocks DNS rebinding.

    Binding to localhost does NOT, by itself, keep a browser-based attacker out.
    In a DNS-rebinding attack a page on evil.example.com re-resolves its own
    domain to 127.0.0.1; the victim's browser then issues same-origin requests
    to this server — reading and overwriting the ledger — and, crucially, sends
    `Host: evil.example.com` while doing it.

    Legitimate clients reach this server as `localhost` or by bare IP, never via
    a registered domain name. Accepting only those two forms breaks the attack
    at its one observable tell, and costs nothing: `localhost:8000` and
    `192.168.1.20:8000` both still work.

    A caller wanting a real hostname (behind a reverse proxy, say) should
    terminate at the proxy and let it own access control — see README.
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
        # A registered domain name — the signature of a rebinding attempt.
        return False
    return True


# Sent on every response.
#
# The page loads its script from a file rather than an inline block, so
# script-src can be a strict 'self' with no 'unsafe-inline' escape hatch — an
# injected <script> will not run even if some future edit lets markup through.
# style-src still needs 'unsafe-inline' because the UI sets style="" attributes
# as it builds HTML, and img-src needs https: because matter logos are
# arbitrary user-supplied URLs.
CSP = "; ".join([
    "default-src 'self'",
    "script-src 'self'",
    "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com",
    "font-src 'self' https://fonts.gstatic.com",
    "img-src 'self' data: https:",
    "connect-src 'self'",
    "form-action 'none'",
    "frame-ancestors 'none'",
    "base-uri 'none'",
])

SECURITY_HEADERS = {
    "Content-Security-Policy": CSP,
    # Stop a stored value being sniffed into an executable type.
    "X-Content-Type-Options": "nosniff",
    # Belt-and-braces with frame-ancestors, for anything not reading CSP.
    "X-Frame-Options": "DENY",
    # Client matter names must not leak to third parties via Referer.
    "Referrer-Policy": "no-referrer",
    # This is private client data; never let a shared cache hold it.
    "Cache-Control": "no-store",
}
