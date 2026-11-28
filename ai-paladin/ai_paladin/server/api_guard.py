"""
Request checks for the router's HTTP API.

The router binds to 127.0.0.1 and has no user accounts, so "only this
machine can reach it" was its whole access control. That is not enough: a web
page open in the user's browser runs on this machine too. Before these checks,
a page from any other origin could send a plain-text POST (a "simple" request,
no CORS preflight) to http://127.0.0.1:8722/api/posture or /api/onprem and
change the posture or switch the on-prem model to read/write internet access.
The browser hides the response from that page, but the change still happens.

What is enforced here, for every request:

  Host     must be 127.0.0.1, localhost or [::1] on the router's own port.
           A DNS-rebinding page arrives with its own host name and is refused.
  Origin   if a browser sends one, it must be the router's own origin.

and for every state-changing request (POST):

  Content-Type  must be application/json. Browsers cannot send that type
                cross-origin without a preflight, which this server never
                answers with permission.
  Token         the X-AI-Paladin-Token header must carry the token made when
                this process started. The dashboard receives it inside the
                HTML the router serves; another origin cannot read that page.

Confirmations: a change that policy.yaml marks require_confirmation is not
accepted on a client-sent `confirm: true`. The server answers 409 with a
single-use challenge bound to that exact change, valid for CONFIRM_TTL_S
seconds, and only a request echoing that challenge goes through.

LIMIT, stated plainly: this proves the request came from a client that holds
the token (the dashboard this router served, or a local program that read
it). It does not prove a human clicked: anything running as the same user
can read the dashboard's HTML from loopback. A per-person identity needs an
identity provider this node does not have.
"""

import hmac
import secrets
import threading
import time

TOKEN_HEADER = "X-AI-Paladin-Token"
LOOPBACK_NAMES = ("127.0.0.1", "localhost", "[::1]")
CONFIRM_TTL_S = 120

# One token per process start. Never written to disk or logged.
TOKEN = secrets.token_urlsafe(32)


class Refusal(Exception):
    def __init__(self, status: int, reason: str):
        super().__init__(reason)
        self.status, self.reason = status, reason


def allowed_hosts(port: int) -> set:
    hosts = {"%s:%d" % (h, port) for h in LOOPBACK_NAMES}
    if port == 80:
        hosts |= set(LOOPBACK_NAMES)
    return hosts


def allowed_origins(port: int) -> set:
    return {"http://%s:%d" % (h, port) for h in LOOPBACK_NAMES}


def check(method: str, headers, port: int, token: str = None):
    """Raise Refusal if the request must not be served. `headers` is any
    mapping with .get(); header names are case-insensitive in http.server."""
    host = (headers.get("Host") or "").strip().lower()
    if host not in allowed_hosts(port):
        raise Refusal(403, "Host %r is not this router (only 127.0.0.1, "
                           "localhost or [::1] on port %d)" % (host, port))
    origin = headers.get("Origin")
    if origin is not None and origin.strip().lower() not in allowed_origins(port):
        raise Refusal(403, "cross-origin request from %r refused" % origin)
    if method == "GET":
        return
    ctype = (headers.get("Content-Type") or "").split(";")[0].strip().lower()
    if ctype != "application/json":
        raise Refusal(415, "state-changing requests must be application/json")
    sent = headers.get(TOKEN_HEADER) or ""
    if not hmac.compare_digest(sent.encode("utf-8"),
                               (token or TOKEN).encode("utf-8")):
        raise Refusal(403, "missing or wrong %s" % TOKEN_HEADER)


class ConfirmationRequired(PermissionError):
    """Policy needs a confirmation the request did not carry."""

    def __init__(self, reason: str, challenge: str):
        super().__init__(reason)
        self.challenge = challenge


class Challenges:
    """Single-use confirmation challenges, each bound to one exact change."""

    def __init__(self, ttl_s: int = CONFIRM_TTL_S):
        self.ttl_s = ttl_s
        self._open = {}
        self._lock = threading.Lock()

    def issue(self, key: str) -> str:
        nonce = secrets.token_urlsafe(18)
        now = time.monotonic()
        with self._lock:
            self._open = {n: v for n, v in self._open.items() if v[1] > now}
            self._open[nonce] = (key, now + self.ttl_s)
        return nonce

    def consume(self, nonce, key: str) -> bool:
        if not isinstance(nonce, str) or not nonce:
            return False
        with self._lock:
            entry = self._open.pop(nonce, None)
        return bool(entry and entry[0] == key and entry[1] > time.monotonic())


CONFIRMATIONS = Challenges()
