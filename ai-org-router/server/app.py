"""
AI-Paladin demo server. Python standard library only - no venv, no pip, no
build step. Run it, open the browser, demo.

    python3 -m server.app          # from ai-org-router/

Endpoints
    GET  /                      the chat UI
    GET  /api/config            modes, corpora, palette, node status
    POST /api/classify          dry-run the router. NO model is invoked.
    POST /api/run               execute an approved decision
    GET  /api/events?since=N    polled event stream (tokens, phases, timings)
    GET  /api/notifications     the notification screen's data
    POST /api/notifications/read
    GET  /api/health            on-prem node reachability
    GET  /api/org               subagent roster + availability
    GET  /api/posture           sealed-posture state + guard self-test result
    POST /api/posture           change posture (refused when lock_mode is set)
"""

import contextlib
import json
import os
import threading
import time
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from bigai import simulated as bigai
from bus import metrics
from bus import notifications as bus
from nodes import ollama_worker
from router import dispatch
from nodes.subagents import Org
from security import egress_guard
from router.classifier import CORPORA, Config, list_corpus_files

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
UI_DIR = os.path.join(BASE, "ui", "demo")
PORT = int(os.environ.get("PALADIN_PORT", "8722"))

CFG = Config()
ORG = Org()

# Agent state palette. Chosen so the mapping is intuitive without a legend:
# red stops, green produces, amber deliberates, blue absorbs, purple directs.
PALETTE = {
    "idle":       {"color": "#64748b", "label": "Idle",              "hint": "Dormant, awaiting work"},
    "thinking":   {"color": "#f59e0b", "label": "Thinking",          "hint": "Reasoning about the request"},
    "reading":    {"color": "#3b82f6", "label": "Reading code",      "hint": "Ingesting local files"},
    "retrieving": {"color": "#06b6d4", "label": "Retrieving",        "hint": "Reaching outside for information"},
    "planning":   {"color": "#a855f7", "label": "Planning",          "hint": "Writing plans & checklists, like a manager"},
    "coding":     {"color": "#22c55e", "label": "Writing code",      "hint": "Producing code, like a developer"},
    "error":      {"color": "#ef4444", "label": "Error",             "hint": "Something failed - human needed"},
}

# In-flight decisions awaiting a human decision at the egress gate.
_pending = {}
_pending_lock = threading.Lock()

# Current posture of the NODE, not of a request. Selecting the sovereign mode
# seals the whole process, the way selecting a firewall rule changes the
# firewall rather than one packet.
_posture_lock = threading.Lock()
_posture = {"mode": None}


def locked_mode():
    """Operator pin from policy.yaml. None means the mode bar is live."""
    lm = CFG.policy.get("defaults", {}).get("lock_mode")
    return lm if lm in CFG.modes else None


def set_posture(mode_id: str, actor: str = "ui") -> dict:
    """
    Apply a mode as the node's posture, arming or disarming the egress guard.
    Both transitions are audited; lifting the perimeter is logged louder than
    raising it, because it is the one an auditor will ask about.
    """
    mode = CFG.modes.get(mode_id)
    if not mode:
        raise ValueError("unknown mode %r" % mode_id)
    # Decide under the lock, act outside it. posture_state() takes the same
    # lock, so returning from inside this block would deadlock the node on the
    # most ordinary input there is: clicking the mode that is already selected.
    with _posture_lock:
        was = _posture["mode"]
        changed = was != mode_id
        if changed:
            _posture["mode"] = mode_id
    if not changed:
        return posture_state()

    want_sealed = bool(mode.get("seal_egress"))
    if want_sealed:
        egress_guard.arm("Mode '%s' selected by %s." % (mode_id, actor),
                         actor=actor)
    elif egress_guard.status()["armed"]:
        egress_guard.disarm("Mode changed %s -> %s by %s. Egress is available "
                            "again." % (was, mode_id, actor), actor=actor)
    return posture_state()


def posture_state() -> dict:
    g = egress_guard.status()
    with _posture_lock:
        mode_id = _posture["mode"]
    mode = CFG.modes.get(mode_id, {})
    return {
        "mode": mode_id,
        "sealed": bool(mode.get("seal_egress")),
        "lock_mode": locked_mode(),
        "guard": {
            "installed": g["installed"],
            "verified": g["verified"],
            "armed": g["armed"],
            "since": g["since"],
            "reason": g["reason"],
            "blocks": g["blocks"],
            "last_block": g["last_block"],
            "scope": "loopback only (127.0.0.0/8, ::1, AF_UNIX)",
            "self_test": g["self_test"],
        },
    }


def onprem_health() -> dict:
    node = CFG.nodes.get("onprem", {})
    url = node.get("endpoint", "http://localhost:11434") + "/api/tags"
    try:
        with urllib.request.urlopen(url, timeout=3) as r:
            data = json.loads(r.read().decode("utf-8"))
        names = [m["name"] for m in data.get("models", [])]
        want = node.get("ollama_model")
        return {"online": True, "models": names, "model_present": want in names,
                "model": want}
    except (urllib.error.URLError, OSError, ValueError, KeyError) as exc:
        return {"online": False, "error": str(exc), "model": node.get("ollama_model")}


# ---------------------------------------------------------------------------
# Execution
# ---------------------------------------------------------------------------

def execute(decision: dict, prompt: str, corpus_id: str):
    """Run an approved decision on whichever node it was routed to."""
    task_id = decision["task_id"]
    # A task DECIDED under a sealed posture EXECUTES under one, even if the
    # node's posture is changed while the task is in flight.
    seal = (egress_guard.sealed_thread() if decision.get("sealed")
            else contextlib.nullcontext())
    try:
        with seal:
            if decision["target"] == "onprem":
                staged = [f["path"] for f in decision.get("staged", {}).get("files", [])]
                if not staged:
                    from router.classifier import rank_relevant_files
                    staged = [c["path"] for c in rank_relevant_files(prompt, corpus_id)[:3]]
                bus.notify("routing.local", "Handled on-prem",
                           decision["reason"], severity="info", task_id=task_id)
                ollama_worker.run(prompt, CFG, task_id, staged_files=staged,
                                  corpus_id=corpus_id)
            else:
                staged = decision.get("staged", {})
                # Order matters: ask the guard before writing the receipt. An
                # "N bytes transmitted" record for bytes that never moved is a
                # false entry in the audit log, and a false entry is worse
                # than a missing one.
                egress_guard.assert_egress_allowed("BIG-AI gateway")
                bus.notify("egress.approved",
                           "Data left on-prem for BIG-AI",
                           "%d bytes transmitted (%d file%s). Approved by human "
                           "at the egress gate. Mode: %s."
                           % (staged.get("total_bytes", 0),
                              len(staged.get("files", [])),
                              "" if len(staged.get("files", [])) == 1 else "s",
                              decision["mode"]),
                           severity="warning", task_id=task_id,
                           payload_bytes=staged.get("total_bytes", 0),
                           files=[f["path"] for f in staged.get("files", [])])
                bigai.run(prompt, CFG, task_id, staged)
    except Exception as exc:                      # demo must never hard-crash
        bus.emit("phase", task_id=task_id, phase="error", detail=str(exc))
        bus.notify("agent.error", "Task failed", str(exc),
                   severity="critical", task_id=task_id)
        bus.emit("done", task_id=task_id, source=decision["target"],
                 elapsed_s=0, error=str(exc))


# ---------------------------------------------------------------------------
# HTTP
# ---------------------------------------------------------------------------

class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    server_version = "AI-Paladin/0.1"

    def log_message(self, fmt, *args):
        pass  # keep the demo console clean

    # -- helpers ----------------------------------------------------------
    def _send(self, code, body, ctype="application/json"):
        if isinstance(body, (dict, list)):
            body = json.dumps(body).encode("utf-8")
        elif isinstance(body, str):
            body = body.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _body(self) -> dict:
        n = int(self.headers.get("Content-Length") or 0)
        if not n:
            return {}
        try:
            return json.loads(self.rfile.read(n).decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            return {}

    def _query(self) -> dict:
        from urllib.parse import parse_qs, urlparse
        return {k: v[0] for k, v in
                parse_qs(urlparse(self.path).query).items()}

    def _path(self) -> str:
        return self.path.split("?")[0]

    def _actor(self) -> str:
        """
        Who moved the perimeter. The demo binds to loopback and has no auth, so
        this is the client address, not an identity - an audit record that
        names a real user needs an identity provider this node does not have.
        """
        return "client:%s" % (self.client_address[0]
                              if self.client_address else "unknown")

    # -- routes -----------------------------------------------------------
    def do_GET(self):
        p = self._path()

        if p in ("/", "/index.html"):
            try:
                with open(os.path.join(UI_DIR, "index.html"), "rb") as fh:
                    return self._send(200, fh.read(), "text/html; charset=utf-8")
            except OSError:
                return self._send(404, {"error": "ui/demo/index.html missing"})

        if p == "/api/config":
            health = onprem_health()
            return self._send(200, {
                "modes": CFG.policy.get("modes", []),
                "invariant": CFG.policy.get("invariant", {}),
                "nodes": CFG.nodes,
                "palette": PALETTE,
                "topics": CFG.policy.get("notifications", {}).get("topics", []),
                "corpora": [
                    {"id": c["id"], "label": c["label"], "safe": c["safe"],
                     "file_count": len(list_corpus_files(c["id"]))}
                    for c in CORPORA.values()
                ],
                "keyword_groups": [
                    {"group": g["group"], "label": g["label"],
                     "severity": g["severity"], "count": len(g.get("terms", [])),
                     "terms": g.get("terms", [])}
                    for g in CFG.groups
                ],
                "keyword_count": CFG.term_count(),
                "protected_paths": CFG.protected_paths,
                "roadmap": CFG.keywords.get("rules_engine_roadmap", {}),
                "defaults": CFG.policy.get("defaults", {}),
                "posture": posture_state(),
                "onprem_health": health,
                "seq": bus.current_seq(),
            })

        if p == "/api/events":
            q = self._query()
            return self._send(200, {"events": bus.since(int(q.get("since", 0))),
                                    "seq": bus.current_seq()})

        if p == "/api/notifications":
            return self._send(200, {"notifications": bus.notifications(),
                                    "unread": len(bus.notifications(True))})

        if p == "/api/org":
            return self._send(200, ORG.status())

        if p == "/api/metrics":
            return self._send(200, metrics.snapshot(CFG.policy.get("pricing", {})))

        if p == "/api/posture":
            return self._send(200, posture_state())

        if p == "/api/health":
            return self._send(200, onprem_health())

        if p == "/api/corpus":
            q = self._query()
            cid = q.get("corpus", "alpha-ip")
            return self._send(200, {"files": list_corpus_files(cid)})

        return self._send(404, {"error": "not found"})

    def do_POST(self):
        p = self._path()
        data = self._body()

        # --- posture change. Arms or disarms the egress guard. -----------
        if p == "/api/posture":
            want = data.get("mode")
            pinned = locked_mode()
            if pinned and want != pinned:
                bus.notify("posture.released" if want else "agent.error",
                           "Posture change refused",
                           "This node is pinned to '%s' by defaults.lock_mode "
                           "in router/policy.yaml. A request to switch to %r "
                           "was refused at the API." % (pinned, want),
                           severity="critical")
                return self._send(409, {"error": "posture is pinned",
                                        "lock_mode": pinned,
                                        "posture": posture_state()})
            try:
                return self._send(200, set_posture(want, actor=self._actor()))
            except ValueError as exc:
                return self._send(400, {"error": str(exc)})
            except egress_guard.EgressBlocked as exc:
                # Fail closed: an unverified guard means no sealed posture.
                return self._send(503, {"error": str(exc),
                                        "posture": posture_state()})

        # --- dry run. No model touched, no socket opened. ----------------
        if p == "/api/classify":
            prompt = (data.get("prompt") or "").strip()
            if not prompt:
                return self._send(400, {"error": "empty prompt"})

            # The mode bar is a UI affordance; the pin is enforced here, where
            # a hand-rolled curl lands too.
            pinned = locked_mode()
            requested = data.get("mode", "slow")
            if pinned and requested != pinned:
                return self._send(409, {"error": "posture is pinned to '%s'"
                                                 % pinned, "lock_mode": pinned})
            if requested != posture_state()["mode"]:
                set_posture(requested, actor=self._actor())

            decision = dispatch.decide(
                prompt, requested, CFG,
                corpus_id=data.get("corpus", "alpha-ip"),
                user_requested_escalation=bool(data.get("escalate")))
            d = decision.to_dict()

            # Tier-1 triage: a 0.6B model labels the task so per-type policy
            # can apply without waking the 24B. ~370ms, against a 60s task.
            clerk = ORG.get("clerk")
            if clerk:
                d["triage"] = clerk.classify(prompt, d["task_id"])

            with _pending_lock:
                _pending[d["task_id"]] = {"decision": d, "prompt": prompt,
                                          "corpus": data.get("corpus", "alpha-ip")}

            metrics.record_decision(d)

            if d.get("sealed") and not d["classification"]["matched"]:
                bus.notify("posture.sealed", "Handled on-prem - posture sealed",
                           d["reason"], severity="info", task_id=d["task_id"])
            elif d["locked"]:
                bus.notify("routing.local", "Protected IP - pinned on-prem",
                           d["reason"], severity="info", task_id=d["task_id"],
                           terms=sorted({m["term"] for m in
                                         d["classification"]["matches"]}))
            elif d["requires_confirmation"]:
                bus.notify("egress.pending",
                           "Awaiting your decision: this will leave on-prem",
                           "%d bytes staged for BIG-AI in mode '%s'. Nothing "
                           "has been sent."
                           % (d.get("staged", {}).get("total_bytes", 0), d["mode"]),
                           severity="warning", task_id=d["task_id"])
            return self._send(200, d)

        # --- commit -------------------------------------------------------
        if p == "/api/run":
            task_id = data.get("task_id")
            with _pending_lock:
                entry = _pending.get(task_id)
            if not entry:
                return self._send(404, {"error": "unknown or expired task_id"})
            if entry["decision"]["target"] == "bigai":
                # The posture can change between staging a payload and
                # approving it. The perimeter that is up NOW decides.
                if egress_guard.is_armed():
                    with _pending_lock:
                        _pending.pop(task_id, None)
                    bus.notify("egress.blocked",
                               "Approved egress refused - perimeter is sealed",
                               "This task was staged for BIG-AI under a "
                               "permissive posture and approved by a human, "
                               "but the node has been sealed since. %d bytes "
                               "were NOT transmitted."
                               % entry["decision"].get("staged", {})
                                    .get("total_bytes", 0),
                               severity="critical", task_id=task_id)
                    metrics.record_block()
                    return self._send(409, {
                        "error": "sovereign posture is armed; egress refused",
                        "task_id": task_id, "posture": posture_state()})
                metrics.record_egress(entry["decision"].get("staged", {}),
                                      approved=True, task_id=task_id)
            threading.Thread(
                target=execute,
                args=(entry["decision"], entry["prompt"], entry["corpus"]),
                daemon=True).start()
            return self._send(200, {"started": True, "task_id": task_id})

        if p == "/api/deny":
            task_id = data.get("task_id")
            with _pending_lock:
                entry = _pending.pop(task_id, None)
            if entry:
                metrics.record_egress(entry["decision"].get("staged", {}),
                                      approved=False, task_id=task_id)
                bus.notify("egress.denied", "Egress denied by human",
                           "Nothing was transmitted. The task was cancelled at "
                           "the gate.", severity="info", task_id=task_id)
            return self._send(200, {"denied": True})

        if p == "/api/notifications/read":
            bus.mark_all_read()
            return self._send(200, {"ok": True})

        if p == "/api/reload":
            CFG.reload()
            bus.notify("routing.local", "Rules reloaded",
                       "keywords.yaml and policy.yaml re-read from disk. "
                       "%d protected terms active." % CFG.term_count(),
                       severity="info")
            return self._send(200, {"ok": True, "terms": CFG.term_count()})

        return self._send(404, {"error": "not found"})


def prewarm():
    """Keep dev-mistral-2 resident. A cold 15GB load is ~35s of dead air."""
    node = CFG.nodes.get("onprem", {})
    body = json.dumps({"model": node.get("ollama_model"), "prompt": "hi",
                       "stream": False, "keep_alive": node.get("keep_alive", "60m"),
                       "options": {"num_predict": 1}}).encode()
    while True:
        try:
            req = urllib.request.Request(
                node.get("endpoint", "http://localhost:11434") + "/api/generate",
                data=body, headers={"Content-Type": "application/json"})
            urllib.request.urlopen(req, timeout=180).read()
        except (urllib.error.URLError, OSError):
            pass
        time.sleep(600)


def boot_guard() -> dict:
    """
    Install the egress guard and prove it works before anything relies on it.

    The self-test deliberately attempts a real outbound connection to
    192.0.2.1 (RFC 5737 TEST-NET-1 - unroutable, so no packet reaches anyone
    even in the failure case) and requires that it be refused. It also
    requires that loopback still be permitted, because a guard that blocks
    everything would pass the first check while taking the on-prem model
    offline with it.

    If the test fails the guard is left unverified and arm() refuses, so the
    sovereign mode becomes unavailable rather than unenforced. Claiming a
    perimeter you have not demonstrated is the failure mode this whole
    product exists to argue against.
    """
    egress_guard.install()
    return egress_guard.self_test()


def main():
    health = onprem_health()
    guard = boot_guard()
    pinned = locked_mode()

    print("\n  AI-Paladin router demo")
    print("  " + "-" * 52)
    print("  on-prem   dev-mistral-2 (%s)" % CFG.nodes["onprem"]["ollama_model"])
    print("            %s" % ("ONLINE" if health["online"] else
                              "OFFLINE - start ollama"))
    print("  BIG-AI    SIMULATED (no ANTHROPIC_API_KEY on this node)")
    print("  rules     %d protected terms, %d protected paths"
          % (CFG.term_count(), len(CFG.protected_paths)))
    print("  guard     egress self-test %s  (probe %s)"
          % ("PASSED" if guard["passed"] else "FAILED", guard["probe"]))
    for c in guard["checks"]:
        print("            [%s] %-18s %s"
              % ("ok" if c["passed"] else "XX", c["check"], c["detail"]))
    if not guard["passed"]:
        print("            sovereign mode UNAVAILABLE - guard unverified")
    print("  posture   %s" % ("PINNED to '%s' by defaults.lock_mode" % pinned
                              if pinned else "selectable, every change audited"))
    print("  " + "-" * 52)
    print("  http://localhost:%d\n" % PORT)

    threading.Thread(target=prewarm, daemon=True).start()
    bus.notify("routing.local", "AI-Paladin router online",
               "Invariant active: protected-IP keyword match pins execution to "
               "on-prem in every mode.", severity="info")

    # Bind before sealing: server_bind() resolves its own listen address, and
    # the guard has no way to tell that lookup apart from an outbound one.
    httpd = ThreadingHTTPServer(("127.0.0.1", PORT), Handler)

    # Apply the starting posture. An operator pin wins over the default, and
    # sealing at boot means the perimeter is up before the first prompt.
    start_mode = pinned or CFG.policy.get("defaults", {}).get("mode", "slow")
    try:
        set_posture(start_mode, actor="boot")
    except (ValueError, egress_guard.EgressBlocked) as exc:
        print("  could not enter posture %r: %s" % (start_mode, exc))

    httpd.serve_forever()


if __name__ == "__main__":
    main()
