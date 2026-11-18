"""
Egress guard - the enforcement half of the sovereign posture.

Every other gate in this repository decides *what* is allowed to leave. This
one decides *whether the socket opens at all*, and it is the only gate that
does not consult a policy file at call time: once armed, the answer for any
destination that is not this machine is no.

    slow / fast / superfast   route around the risk
    sovereign                 removes the capability

WHAT IS ENFORCED (MVP)
    Loopback only, hard-coded. 127.0.0.0/8, ::1, and AF_UNIX sockets - none of
    which can put a packet on a wire. Everything else is refused before the
    connect() syscall, including DNS: name resolution is itself egress, so a
    hostname that is not a loopback literal is refused rather than resolved.

WHAT IS NOT ENFORCED, STATED PLAINLY
    This is a process-level guard, not a host-level one. It covers this Python
    process: socket.socket.connect/connect_ex/sendto, socket.create_connection
    and socket.getaddrinfo, which is every path urllib, http.client and the
    ollama adapter actually take. It does NOT cover a child process, a raw
    _socket.socket built to dodge it, or anything else running on the box.
    Production containment is a host firewall or a network namespace with no
    default route; this guard is what makes the posture demonstrable and
    fail-closed inside the router itself. Do not describe it as an air gap.

FAIL-CLOSED
    arm() refuses unless self_test() has proved the guard actually blocks. A
    posture that cannot demonstrate enforcement is not entered.

ROADMAP
    The perimeter is meant to widen to the LAN - a second on-prem node, a
    pooled GPU box - without ever widening to the internet. That is a change
    to _is_local(), not to this module's shape. See docs/ROADMAP.md section 5.
"""

import ipaddress
import socket
import threading
from datetime import datetime, timezone

from bus import metrics
from bus import notifications as bus


class EgressBlocked(OSError):
    """Raised in place of a connection the sovereign posture forbids."""


# Hostnames that cannot resolve off-box. Anything else must be a loopback
# literal - we will not run a DNS query to find out, because that query is
# itself a packet leaving the machine.
LOCAL_NAMES = {"localhost", "localhost.localdomain", "ip6-localhost",
               "ip6-loopback"}

# RFC 5737 TEST-NET-1. Unroutable by design, so the self-test probe sends a
# packet precisely nowhere even in the failure case it is testing for.
PROBE_ADDR = ("192.0.2.1", 443)

_state = {
    "installed": False,
    "verified": False,
    "armed": False,
    "reason": "",
    "since": None,
    "blocks": 0,
    "last_block": None,
    "self_test": None,
}
_lock = threading.Lock()
_tls = threading.local()          # per-thread arm, for a single sealed task

_real = {}


# ---------------------------------------------------------------------------
# Destination classification
# ---------------------------------------------------------------------------

def _is_local_ip(host: str) -> bool:
    try:
        ip = ipaddress.ip_address(str(host).split("%", 1)[0])
    except ValueError:
        return False
    if ip.is_loopback:
        return True
    # ::ffff:127.0.0.1 is loopback wearing an IPv6 coat.
    mapped = getattr(ip, "ipv4_mapped", None)
    return bool(mapped and mapped.is_loopback)


def _describe(family, address) -> str:
    if family == getattr(socket, "AF_UNIX", None):
        return "unix:%s" % (address,)
    try:
        return "%s:%s" % (address[0], address[1])
    except (TypeError, IndexError):
        return repr(address)


def _permitted(family, address):
    """(allowed, why). The whole policy, in one function, deliberately."""
    if family == getattr(socket, "AF_UNIX", None):
        return True, "AF_UNIX socket - local IPC, no wire involved"
    if address is None:
        return True, "no destination"
    host = address[0] if isinstance(address, (tuple, list)) else address
    if host in (None, ""):
        return True, "unspecified host"
    if str(host).lower() in LOCAL_NAMES:
        return True, "loopback by name"
    if _is_local_ip(host):
        return True, "loopback address"
    try:
        ipaddress.ip_address(str(host).split("%", 1)[0])
    except ValueError:
        return False, ("%r is a hostname, not a loopback literal - resolving "
                       "it would itself be egress" % host)
    return False, "%r is not on this machine" % host


# ---------------------------------------------------------------------------
# Arming
# ---------------------------------------------------------------------------

def is_armed() -> bool:
    return bool(_state["armed"] or getattr(_tls, "armed", False))


def status() -> dict:
    with _lock:
        return dict(_state, armed_now=is_armed())


def arm(reason: str = "", actor: str = "operator") -> dict:
    """
    Enter the sovereign posture process-wide. Fails closed: an unverified
    guard is not a perimeter, so we refuse to claim one.
    """
    if not _state["verified"]:
        raise EgressBlocked(
            "egress guard is not verified - refusing to enter the sovereign "
            "posture. A posture that cannot prove it blocks is a label.")
    with _lock:
        if _state["armed"]:
            return dict(_state)
        _state["armed"] = True
        _state["reason"] = reason
        _state["since"] = datetime.now(timezone.utc).isoformat()
    bus.notify("posture.sealed", "Sovereign posture armed",
               "Outbound network access is now refused at the socket for this "
               "process. Loopback only. %s" % reason,
               severity="warning", actor=actor)
    bus.emit("posture", posture="sovereign", armed=True, actor=actor,
             detail=reason)
    return status()


def disarm(reason: str = "", actor: str = "operator") -> dict:
    """
    Leave the sovereign posture. This is the security-relevant transition, so
    it is logged at critical severity with the actor named - lifting a
    perimeter should be at least as loud as raising one.
    """
    with _lock:
        if not _state["armed"]:
            return dict(_state)
        held = _state["since"]
        _state["armed"] = False
        _state["reason"] = ""
        _state["since"] = None
    bus.notify("posture.released", "Sovereign posture LIFTED",
               "Outbound network access is available again. Held since %s. "
               "%s" % (held, reason), severity="critical", actor=actor)
    bus.emit("posture", posture="open", armed=False, actor=actor,
             detail=reason)
    return status()


class sealed_thread:
    """
    Arm the guard for the calling thread only, for the life of a single task.

    Belt and braces next to the process-wide flag: a task that was *decided*
    under the sovereign posture executes under it too, even if someone flips
    the mode mid-flight.
    """

    def __enter__(self):
        self._prev = getattr(_tls, "armed", False)
        _tls.armed = True
        return self

    def __exit__(self, *exc):
        _tls.armed = self._prev
        return False


# ---------------------------------------------------------------------------
# Enforcement
# ---------------------------------------------------------------------------

def _refuse(where: str, dest: str, why: str):
    probe = getattr(_tls, "self_test", False)
    if not probe:
        with _lock:
            _state["blocks"] += 1
            _state["last_block"] = {"where": where, "dest": dest, "why": why,
                                    "ts": datetime.now(timezone.utc).isoformat()}
        metrics.record_block()
    # The event goes to the audit sink either way - a block we inflicted on
    # ourselves is still a block, and hiding it would make the log a summary
    # rather than a record. What a self-test probe does NOT do is raise a
    # critical notification or move the ledger: it was not an agent being
    # refused, and the demo should not open on two unexplained criticals.
    bus.emit("policy", gate="egress_guard#sovereign", outcome="blocked",
             self_test=probe,
             detail="%s -> %s refused: %s" % (where, dest, why))
    if not probe:
        bus.notify("egress.blocked", "Outbound connection refused at the socket",
                   "Sovereign posture is armed. %s to %s was refused before the "
                   "syscall: %s" % (where, dest, why), severity="critical")
    raise EgressBlocked(
        "sovereign posture: %s to %s refused (%s)" % (where, dest, why))


def _check(family, address, where: str):
    if not is_armed():
        return
    allowed, why = _permitted(family, address)
    if not allowed:
        _refuse(where, _describe(family, address), why)


def assert_egress_allowed(purpose: str = "egress"):
    """
    Semantic check for code paths that would egress without opening a socket
    themselves - the simulated BIG-AI adapter being the one that matters. A
    stub that "succeeds" under a sealed posture would be a lie in the audit
    log, which is worse than a stub.
    """
    if is_armed():
        _refuse("adapter", purpose, "no destination outside this machine is "
                                    "reachable under the sovereign posture")


# ---------------------------------------------------------------------------
# Installation
# ---------------------------------------------------------------------------

def install() -> dict:
    """Patch the socket surface. Idempotent."""
    if _state["installed"]:
        return status()

    _real["connect"] = socket.socket.connect
    _real["connect_ex"] = socket.socket.connect_ex
    _real["sendto"] = socket.socket.sendto
    _real["getaddrinfo"] = socket.getaddrinfo
    _real["gethostbyname"] = socket.gethostbyname
    _real["gethostbyaddr"] = socket.gethostbyaddr

    def guarded_connect(sock, address):
        _check(sock.family, address, "connect")
        return _real["connect"](sock, address)

    def guarded_connect_ex(sock, address):
        # Contractually this returns an errno rather than raising. We raise
        # anyway: a silent error code is exactly how a blocked egress attempt
        # becomes an unexplained retry loop instead of an audit record.
        _check(sock.family, address, "connect_ex")
        return _real["connect_ex"](sock, address)

    def guarded_sendto(sock, data, *args):
        if args:
            _check(sock.family, args[-1], "sendto")
        return _real["sendto"](sock, data, *args)

    def guarded_getaddrinfo(host, port, family=0, type=0, proto=0, flags=0):
        if is_armed() and host not in (None, ""):
            allowed, why = _permitted(socket.AF_INET, (host, port))
            if not allowed:
                _refuse("getaddrinfo", "%s:%s" % (host, port), why)
        return _real["getaddrinfo"](host, port, family, type, proto, flags)

    socket.socket.connect = guarded_connect
    socket.socket.connect_ex = guarded_connect_ex
    socket.socket.sendto = guarded_sendto
    def _guarded_resolver(name):
        """gethostbyname / gethostbyaddr share one shape and one rule."""
        def wrapper(host, *a, **kw):
            if is_armed() and host not in (None, ""):
                allowed, why = _permitted(socket.AF_INET, (host, 0))
                if not allowed:
                    _refuse(name, str(host), why)
            return _real[name](host, *a, **kw)
        return wrapper

    # create_connection() resolves through the module-global getaddrinfo and
    # then calls sock.connect(), so both of its legs are already covered.
    socket.getaddrinfo = guarded_getaddrinfo
    socket.gethostbyname = _guarded_resolver("gethostbyname")
    socket.gethostbyaddr = _guarded_resolver("gethostbyaddr")

    _state["installed"] = True
    return status()


def self_test() -> dict:
    """
    Prove the guard blocks, before anything relies on it.

    Four assertions. Each exercises a different patched entry point, because
    a guard that covers connect() but not the resolver is not a perimeter -
    and because two of these can pass for the wrong reason:

      1. connect() to a literal address is refused
      2. create_connection() - the path urllib actually takes - is refused
      3. name resolution is refused          - DNS is egress too
      4. loopback is still PERMITTED         - a guard that blocked everything
                                               would pass 1-3 while taking the
                                               on-prem model offline with it
    """
    if not _state["installed"]:
        install()

    def probe(name, fn, expected: str):
        try:
            fn()
            return (name, False, "%s was NOT blocked" % expected)
        except EgressBlocked:
            return (name, True, "%s refused, no packet sent" % expected)
        except OSError as exc:
            return (name, False,
                    "reached the network stack (%s) - guard did not fire" % exc)

    def raw_connect():
        sk = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sk.settimeout(1)
        try:
            sk.connect(PROBE_ADDR)
        finally:
            sk.close()

    checks = []
    _tls.self_test = True
    try:
        with sealed_thread():
            checks.append(probe(
                "socket-connect", raw_connect,
                "connect() to %s:%d" % PROBE_ADDR))
            checks.append(probe(
                "create-connection",
                lambda: socket.create_connection(PROBE_ADDR, timeout=1).close(),
                "urllib's create_connection() to %s:%d" % PROBE_ADDR))
            checks.append(probe(
                "dns-resolution",
                lambda: socket.getaddrinfo("example.com", 443),
                "getaddrinfo('example.com')"))
            ok, why = _permitted(socket.AF_INET, ("127.0.0.1", 11434))
            checks.append(("loopback-permitted", ok,
                           "on-prem model reachable: %s" % why if ok else
                           "loopback wrongly refused - the guard is too wide"))
    finally:
        _tls.self_test = False

    passed = all(ok for _, ok, _ in checks)
    result = {
        "passed": passed,
        "probe": "%s:%d (RFC 5737 TEST-NET-1, unroutable)" % PROBE_ADDR,
        "checks": [{"check": n, "passed": ok, "detail": d}
                   for n, ok, d in checks],
        "ts": datetime.now(timezone.utc).isoformat(),
    }
    with _lock:
        _state["verified"] = passed
        _state["self_test"] = result
        # The probes above were real blocks and are in the audit log, but they
        # were self-inflicted. Counting them would open the demo showing
        # "2 outbound attempts refused" before anyone had typed a prompt.
        _state["blocks"] = 0
        _state["last_block"] = None

    bus.notify("posture.sealed" if passed else "agent.error",
               "Egress guard self-test %s" % ("passed" if passed else "FAILED"),
               "; ".join("%s: %s" % (n, d) for n, _, d in checks),
               severity="info" if passed else "critical")
    return result
