"""Same-origin boundary for the local Web/API surface (AS-02).

The ASGI server address is trusted transport metadata, never a forwarded header.
Non-browser clients without Origin/Referer must send a non-simple JSON content
type, a valid explicit Bearer credential, or X-AllSpark-Request: 1. We do not
enable CORS, so foreign pages cannot satisfy that contract through preflight.
"""
import hmac
from urllib.parse import urlsplit

from starlette.requests import Request


def _origin(value: str, *, referer: bool = False) -> tuple[str, str, int] | None:
    try:
        parsed = urlsplit(value)
        if (parsed.scheme not in {"http", "https"} or not parsed.hostname
                or parsed.username is not None or parsed.password is not None
                or any(char.isspace() for char in value)
                or (not referer and (parsed.path or parsed.query or parsed.fragment))):
            return None
        return parsed.scheme, parsed.hostname.lower(), parsed.port or (443 if parsed.scheme == "https" else 80)
    except ValueError:
        return None


def request_boundary_error(request: Request) -> str | None:
    hosts = request.headers.getlist("host")
    if len(hosts) != 1:
        return "untrusted_host"
    target = _origin(f"{request.scope.get('scheme', 'http')}://{hosts[0]}")
    server = request.scope.get("server")
    trusted_hosts = {"localhost", "127.0.0.1", "::1"}
    if server:
        trusted_hosts.add(server[0].lower())
    if target is None or target[1] not in trusted_hosts:
        return "untrusted_host"
    # Reject a spoofed authority port as well; reverse proxy aliases are not a
    # supported deployment contract and forwarded headers never expand trust.
    if server and target[2] != server[1]:
        return "untrusted_host"
    site = request.headers.get("sec-fetch-site")
    if site == "cross-site" and request.scope["path"].startswith("/api/"):
        return "cross_origin_request"
    if request.method in {"GET", "HEAD", "OPTIONS"}:
        return None
    origins = request.headers.getlist("origin")
    if origins:
        if len(origins) != 1 or _origin(origins[0]) != target:
            return "cross_origin_request"
        return None
    referers = request.headers.getlist("referer")
    if referers:
        if len(referers) != 1 or _origin(referers[0], referer=True) != target:
            return "cross_origin_request"
        return None
    # An explicit non-simple request marker is a deliberate API-client
    # contract, not an assumption that missing browser headers imply trust.
    token = request.app.state.web_token
    auth = request.headers.get("authorization", "")
    if token and hmac.compare_digest(auth.encode(), f"Bearer {token}".encode()):
        return None
    if request.headers.get("x-allspark-request") == "1":
        return None
    if request.headers.get("content-type", "").split(";", 1)[0].strip().lower() == "application/json":
        return None
    return "cross_origin_request"
