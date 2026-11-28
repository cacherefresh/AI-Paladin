"""
AI-Paladin demo server. Python standard library only - no venv, no pip, no
build step. Run it, open the browser, demo.

    python3 -m server.app          # from ai-paladin/

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
    GET  /api/onprem            model catalog, selected model, internet access
    POST /api/onprem            select a model and/or set internet access
"""

import contextlib
import json
import yaml
import os
import threading
import time
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from ai_paladin.bigai import simulated as bigai
from ai_paladin.bus import metrics
from ai_paladin.bus import notifications as bus
from ai_paladin.nodes import ollama_worker
from ai_paladin.nodes import web_tools
from ai_paladin.router import dispatch
from ai_paladin.nodes.subagents import Org
from ai_paladin.security import egress_guard
from ai_paladin.server import api_guard
from ai_paladin.router.classifier import CORPORA, Config, list_corpus_files

from ai_paladin import config_layers
from ai_paladin.paths import CONFIG_DIR, LOG_DIR, shipped, user_config
UI_DIR = shipped("ui", "demo")
PORT = int(os.environ.get("PALADIN_PORT", "8722"))

CFG = Config()
ORG = Org()

LOCAL_MODELS_PATH = user_config("local_models.yaml")

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


def _installed_models():
    node = CFG.nodes.get("onprem", {})
    url = node.get("endpoint", "http://localhost:11434") + "/api/tags"
    with urllib.request.urlopen(url, timeout=3) as r:
        data = json.loads(r.read().decode("utf-8"))
    return [m["name"] for m in data.get("models", [])]


def _same_tag(a: str, b: str) -> bool:
    """'flint' and 'flint:latest' name the same model."""
    norm = lambda t: t if ":" in t.rsplit("/", 1)[-1] else t + ":latest"
    return norm(a) == norm(b)


def onprem_health() -> dict:
    want = selected_model()["id"]
    try:
        names = _installed_models()
        return {"online": True, "models": names,
                "model_present": any(_same_tag(want, n) for n in names),
                "model": want}
    except (urllib.error.URLError, OSError, ValueError, KeyError) as exc:
        return {"online": False, "error": str(exc), "model": want}


# ---------------------------------------------------------------------------
# On-prem model selection and internet access
# ---------------------------------------------------------------------------
# The model is a per-machine preference, persisted to config/local_models.yaml
# (gitignored; docs/ROADMAP.md section 8). Internet access is NOT persisted:
# every boot starts at policy.yaml's internet_access.default, so a read/write
# setting cannot quietly survive a restart.

_onprem_lock = threading.Lock()
_onprem = {"model": None, "internet": None, "toggles": {}}


def load_catalog() -> dict:
    try:
        cat = config_layers.load_whole("catalog.yaml")[0]
    except OSError:
        cat = {}
    allow = set(cat.get("license_allowlist") or [])
    for m in cat.get("models", []):
        m["license_ok"] = m.get("license") in allow
    return cat


def _catalog_entry(tag: str):
    for m in load_catalog().get("models", []):
        if _same_tag(m["id"], tag):
            return m
    return None


def _fallback_entry() -> dict:
    node = CFG.nodes.get("onprem", {})
    return {"id": node.get("ollama_model", "devstral-small-2:latest"),
            "name": node.get("model", "dev-mistral-2"),
            "capabilities": ["tools"], "max_tokens": 420, "labels": [],
            "license_ok": True}


def selected_model() -> dict:
    with _onprem_lock:
        tag = _onprem["model"]
    return (_catalog_entry(tag) if tag else None) or _fallback_entry()


def _ia() -> dict:
    return CFG.policy.get("internet_access", {}) or {}


def internet_modes() -> dict:
    return {m["id"]: m for m in _ia().get("modes", [])}


def internet_lock():
    lk = _ia().get("lock")
    return lk if lk in internet_modes() else None


def method_toggles() -> list:
    return web_tools.method_toggles(CFG.policy)


def method_summary(mode: str, toggles: dict) -> dict:
    """What a setting may send, and everything it may not, by name."""
    allowed = web_tools.methods_for(mode, CFG.policy, toggles)
    known = web_tools.KNOWN_METHODS - {"*"}
    return {"allowed": sorted(allowed), "blocked": sorted(known - allowed),
            "known": len(known)}


def effective_internet(protected: bool = False, sealed: bool = False) -> dict:
    """
    The setting a task actually runs with. Most restrictive wins, and the
    reason is returned so the UI and the audit log can say why.
    """
    with _onprem_lock:
        chosen = _onprem["internet"] or "off"
        toggles = dict(_onprem["toggles"])
    if sealed or egress_guard.is_armed():
        out = {"mode": "off", "chosen": chosen,
               "why": "sovereign posture is armed - no external network"}
    elif protected and chosen == "readwrite":
        out = {"mode": "read", "chosen": chosen,
               "why": "protected-IP task - read/write lowered to read-only"}
    else:
        out = {"mode": chosen, "chosen": chosen, "why": ""}
    # The task's receipt records the toggles and the resulting method list,
    # so the audit trail says exactly what the model could send.
    out["toggles"] = toggles
    out["methods"] = sorted(web_tools.methods_for(out["mode"], CFG.policy,
                                                  toggles))
    return out


def _boot_onprem():
    cat = load_catalog()
    saved = {}
    try:
        with open(LOCAL_MODELS_PATH, "r", encoding="utf-8") as fh:
            saved = (yaml.safe_load(fh) or {}).get("onprem", {}) or {}
    except OSError:
        pass
    model = saved.get("model") or cat.get("default")
    try:
        names = _installed_models()
    except (urllib.error.URLError, OSError, ValueError, KeyError):
        names = []
    entry = _catalog_entry(model) if model else None
    if not entry or not entry.get("license_ok") or (
            names and not any(_same_tag(entry["id"], n) for n in names)):
        model = cat.get("fallback") or _fallback_entry()["id"]
    default = internet_lock() or _ia().get("default", "read")
    with _onprem_lock:
        _onprem["model"] = model
        _onprem["internet"] = default if default in internet_modes() else "off"
        # Like the internet setting, toggles are not persisted: every boot
        # starts at policy.yaml's defaults.
        _onprem["toggles"] = web_tools.toggle_defaults(CFG.policy)


def _persist_model(tag: str):
    os.makedirs(os.path.dirname(LOCAL_MODELS_PATH), exist_ok=True)
    with open(LOCAL_MODELS_PATH, "w", encoding="utf-8") as fh:
        fh.write("# Per-machine model selection, written by the dashboard. "
                 "Gitignored.\n")
        yaml.safe_dump({"onprem": {"model": tag}}, fh, sort_keys=False)


def onprem_state() -> dict:
    cat = load_catalog()
    try:
        names = _installed_models()
        online = True
    except (urllib.error.URLError, OSError, ValueError, KeyError):
        names, online = [], False
    sel = selected_model()
    models = []
    for m in cat.get("models", []):
        installed = any(_same_tag(m["id"], n) for n in names)
        why = ""
        if not m.get("license_ok"):
            why = ("licence %s is not on the allowlist (%s)"
                   % (m.get("license"), ", ".join(cat.get("license_allowlist") or [])))
        elif not installed:
            why = "not downloaded"
        models.append(dict(m, installed=installed, selectable=not why,
                           why=why, pull="ollama pull %s" % m["id"],
                           pull_hf=("ollama pull %s" % m["huggingface"])
                           if m.get("huggingface") else ""))
    eff = effective_internet()
    return {
        "model": sel["id"],
        "model_name": sel.get("name", sel["id"]),
        "ollama_online": online,
        "models": models,
        "labels": cat.get("labels", {}),
        "internet": eff["chosen"],
        "internet_effective": eff["mode"],
        "internet_why": eff["why"],
        "internet_lock": internet_lock(),
        "internet_modes": _ia().get("modes", []),
        "method_toggles": [dict(t, on=bool(eff["toggles"].get(t["id"])))
                           for t in method_toggles()],
        "methods": method_summary(eff["mode"], eff["toggles"]),
        "accounts": len(web_tools.account_names()),
    }


def _swap_model(old: str, new: str):
    """Free the old model's RAM, then load the new one. 96 GB is not infinite."""
    node = CFG.nodes.get("onprem", {})
    url = node.get("endpoint", "http://localhost:11434") + "/api/generate"
    def post(model, keep):
        body = json.dumps({"model": model, "prompt": "hi", "stream": False,
                           "keep_alive": keep,
                           "options": {"num_predict": 1}}).encode()
        try:
            urllib.request.urlopen(urllib.request.Request(
                url, data=body, headers={"Content-Type": "application/json"}),
                timeout=300).read()
        except (urllib.error.URLError, OSError):
            pass
    if old and not _same_tag(old, new):
        post(old, 0)
    bus.emit("phase", phase="thinking", node="onprem-01",
             detail="Loading %s into memory" % new)
    post(new, node.get("keep_alive", "60m"))
    bus.emit("phase", phase="idle", node="onprem-01",
             detail="%s loaded" % new)


def set_onprem(data: dict, actor: str) -> dict:
    """Apply a dashboard change. Raises ValueError with a reason to refuse."""
    want_model = data.get("model")
    want_net = data.get("internet")

    # A confirmation is a single-use challenge the server issued for this
    # exact change (api_guard), never a client-sent `confirm: true`.
    change = json.dumps({k: v for k, v in data.items() if k != "confirm"},
                        sort_keys=True)
    confirmed = []

    def require_confirmation(reason):
        if not confirmed:
            confirmed.append(api_guard.CONFIRMATIONS.consume(
                data.get("confirm"), change))
        if not confirmed[0]:
            raise api_guard.ConfirmationRequired(
                reason, api_guard.CONFIRMATIONS.issue(change))
    if want_model:
        entry = _catalog_entry(want_model)
        if not entry:
            raise ValueError("model %r is not in models/catalog.yaml" % want_model)
        if not entry.get("license_ok"):
            raise ValueError("model %r has licence %s, which is not on the "
                             "catalog's allowlist" % (want_model, entry.get("license")))
        try:
            names = _installed_models()
        except (urllib.error.URLError, OSError, ValueError, KeyError):
            raise ValueError("ollama is not reachable")
        if not any(_same_tag(entry["id"], n) for n in names):
            raise ValueError("model %r is not downloaded. Run: ollama pull %s"
                             % (want_model, entry["id"]))
    if want_net:
        if want_net not in internet_modes():
            raise ValueError("unknown internet access %r" % want_net)
        lk = internet_lock()
        if lk and want_net != lk:
            raise PermissionError("internet access is pinned to '%s' by "
                                  "internet_access.lock in router/policy.yaml" % lk)
        if internet_modes()[want_net].get("require_confirmation"):
            require_confirmation("read/write needs explicit confirmation")
    want_tog = data.get("toggles") or {}
    if not isinstance(want_tog, dict):
        raise ValueError("toggles must be an object of id -> true/false")
    defs = {t["id"]: t for t in method_toggles()}
    for tid, on in want_tog.items():
        if tid not in defs:
            raise ValueError("unknown method toggle %r" % tid)
        if internet_lock() and bool(on) != defs[tid]["default"]:
            raise PermissionError("internet access is pinned by "
                                  "internet_access.lock; method toggles stay "
                                  "at their policy defaults")
        if on and defs[tid].get("require_confirmation"):
            require_confirmation("enabling %s needs explicit confirmation"
                                 % defs[tid].get("label", tid))

    with _onprem_lock:
        old_model, old_net = _onprem["model"], _onprem["internet"]
        old_tog = dict(_onprem["toggles"])
        if want_model:
            _onprem["model"] = entry["id"]
        if want_net:
            _onprem["internet"] = want_net
        for tid, on in want_tog.items():
            _onprem["toggles"][tid] = bool(on)

    if want_model and not _same_tag(old_model or "", entry["id"]):
        _persist_model(entry["id"])
        bus.notify("onprem.changed", "On-prem model changed",
                   "%s -> %s (%s). Changed by %s."
                   % (old_model, entry["id"], entry.get("vendor", ""), actor),
                   severity="info", actor=actor, model=entry["id"])
        threading.Thread(target=_swap_model, args=(old_model, entry["id"]),
                         daemon=True).start()
    if want_net and want_net != old_net:
        m = internet_modes()[want_net]
        sev = {"readwrite": "critical", "read": "warning"}.get(want_net, "info")
        bus.notify("onprem.changed",
                   "On-prem internet access: %s" % m.get("short", want_net),
                   "%s -> %s by %s. %s" % (old_net, want_net, actor,
                                           " ".join(m.get("description", "").split())),
                   severity=sev, actor=actor, internet=want_net)
    for tid, on in want_tog.items():
        if bool(on) == bool(old_tog.get(tid)):
            continue
        t = defs[tid]
        # Widening write access is the event an auditor asks about.
        sev = ("critical" if on and t["writes"] else
               "warning" if on else "info")
        bus.notify("onprem.changed",
                   "Method toggle %s: %s" % (t.get("label", tid),
                                             "ON" if on else "off"),
                   "%s (%s) switched %s by %s."
                   % (t.get("label", tid), ", ".join(t["methods"]),
                      "on" if on else "off", actor),
                   severity=sev, actor=actor, toggle=tid, on=bool(on))
    return onprem_state()


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
                    from ai_paladin.router.classifier import rank_relevant_files
                    staged = [c["path"] for c in rank_relevant_files(prompt, corpus_id)[:3]]
                bus.notify("routing.local", "Handled on-prem",
                           decision["reason"], severity="info", task_id=task_id)
                model = (_catalog_entry(decision.get("onprem_model") or "")
                         or selected_model())
                net = (decision.get("internet") or {}).get("mode", "off")
                toggles = (decision.get("internet") or {}).get("toggles")
                # no-external-network-io is enforced at the socket for this
                # worker thread, not only by withholding the web tools.
                no_net = (egress_guard.sealed_thread(
                              "Internet access is no-external-network-io.")
                          if net == "off" else contextlib.nullcontext())
                with no_net:
                    ollama_worker.run(prompt, CFG, task_id, staged_files=staged,
                                      corpus_id=corpus_id, model=model,
                                      internet=net, toggles=toggles)
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
    def _refused(self, method: str) -> bool:
        """Host, Origin, Content-Type and token checks (api_guard). True if
        the request was refused and answered."""
        try:
            api_guard.check(method, self.headers, PORT)
        except api_guard.Refusal as r:
            if method != "GET":
                bus.notify("agent.error", "API request refused",
                           "%s %s: %s" % (method, self._path(), r.reason),
                           severity="warning")
            n = int(self.headers.get("Content-Length") or 0)
            if n:
                self.rfile.read(n)
            self._send(r.status, {"error": r.reason})
            return True
        return False

    def do_GET(self):
        if self._refused("GET"):
            return
        p = self._path()

        if p in ("/", "/index.html"):
            try:
                with open(os.path.join(UI_DIR, "index.html"), "rb") as fh:
                    html = fh.read().decode("utf-8")
                # The dashboard's copy of this start's API token. Another
                # origin cannot read this page, so it cannot learn the token.
                meta = ('<meta name="ai-paladin-token" content="%s">'
                        % api_guard.TOKEN)
                html = html.replace("<head>", "<head>\n" + meta, 1)
                return self._send(200, html, "text/html; charset=utf-8")
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
                "config": config_state(),
                "onprem_health": health,
                "onprem": onprem_state(),
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
            # The roster names the default engineer; the dashboard's picker
            # overrides it per machine, and the chart shows what really runs.
            org = ORG.status()
            sel = selected_model()
            for a in org.get("agents", []):
                if a.get("id") == "engineer":
                    a["model"] = sel["id"]
                    if sel.get("weights_gb"):
                        a["size_mb"] = int(sel["weights_gb"] * 1000)
            return self._send(200, org)

        if p == "/api/metrics":
            return self._send(200, metrics.snapshot(CFG.policy.get("pricing", {})))

        if p == "/api/posture":
            return self._send(200, posture_state())

        if p == "/api/onprem":
            return self._send(200, onprem_state())

        if p == "/api/health":
            return self._send(200, onprem_health())

        if p == "/api/corpus":
            q = self._query()
            cid = q.get("corpus", "alpha-ip")
            return self._send(200, {"files": list_corpus_files(cid)})

        return self._send(404, {"error": "not found"})

    def do_POST(self):
        if self._refused("POST"):
            return
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

        # --- on-prem model + internet access ----------------------------
        if p == "/api/onprem":
            try:
                return self._send(200, set_onprem(data, self._actor()))
            except api_guard.ConfirmationRequired as exc:
                # The client shows its own confirmation to the person, then
                # repeats the same request with this challenge as `confirm`.
                return self._send(409, {"error": str(exc),
                                        "confirm_challenge": exc.challenge,
                                        "confirm_ttl_s": api_guard.CONFIRM_TTL_S,
                                        "onprem": onprem_state()})
            except PermissionError as exc:
                return self._send(409, {"error": str(exc),
                                        "onprem": onprem_state()})
            except ValueError as exc:
                return self._send(400, {"error": str(exc),
                                        "onprem": onprem_state()})

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

            # Snapshot the on-prem model and internet access the task will run
            # with, after precedence, so the receipt says what actually applied.
            if d["target"] == "onprem":
                d["onprem_model"] = selected_model()["id"]
                d["internet"] = effective_internet(
                    protected=bool(d["classification"]["matched"]),
                    sealed=bool(d.get("sealed")))

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
            try:
                CFG.reload()
            except (config_layers.OverlayError, yaml.YAMLError, OSError) as exc:
                bus.notify("agent.error", "Rules NOT reloaded",
                           "%s. The previous rules are still in force." % exc,
                           severity="critical")
                return self._send(400, {"ok": False, "error": str(exc)})
            bus.notify("routing.local", "Rules reloaded",
                       "keywords.yaml and policy.yaml re-read from disk. "
                       "%d protected terms active." % CFG.term_count(),
                       severity="info")
            return self._send(200, {"ok": True, "terms": CFG.term_count()})

        return self._send(404, {"error": "not found"})


def prewarm():
    """Keep the selected model resident. A cold load is 30s+ of dead air."""
    node = CFG.nodes.get("onprem", {})
    while True:
        body = json.dumps({"model": selected_model()["id"], "prompt": "hi",
                           "stream": False,
                           "keep_alive": node.get("keep_alive", "60m"),
                           "options": {"num_predict": 1}}).encode()
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


def config_state() -> dict:
    """Which files are in force, from where, and what the user weakened."""
    kw = CFG.report["keywords"]
    files = list(kw["sources"]) + [CFG.report["policy"]]
    for name in config_layers.REPLACED_WHOLE:
        if name == "policy.yaml":
            continue                # already listed, from CFG.report
        path, source = config_layers.resolve(name)
        try:
            files.append({"file": name, "path": path, "source": source,
                          "sha256": config_layers.sha256_short(path)})
        except OSError:
            files.append({"file": name, "path": path, "source": "missing",
                          "sha256": ""})
    accounts = user_config("web_accounts.yaml")
    exposed = (os.path.isfile(accounts)
               and os.stat(accounts).st_mode & 0o077 != 0)
    return {"config_dir": CONFIG_DIR, "log_dir": LOG_DIR, "files": files,
            "weakened": kw["weakened"], "strengthened": kw["strengthened"],
            "notes": kw["notes"], "web_accounts_exposed": bool(exposed)}


def main():
    _boot_onprem()
    health = onprem_health()
    guard = boot_guard()
    pinned = locked_mode()

    print("\n  AI-Paladin router demo")
    print("  " + "-" * 52)
    sel = selected_model()
    net = effective_internet()
    print("  on-prem   %s (%s)" % (sel.get("name", sel["id"]), sel["id"]))
    print("            %s" % ("ONLINE" if health["online"] else
                              "OFFLINE - start ollama"))
    print("  internet  %s%s" % (net["mode"],
                                "  (%s)" % net["why"] if net["why"] else ""))
    print("  BIG-AI    SIMULATED (no ANTHROPIC_API_KEY on this node)")
    print("  rules     %d protected terms, %d protected paths"
          % (CFG.term_count(), len(CFG.protected_paths)))
    conf = config_state()
    for f in conf["files"]:
        print("            %-21s %-12s %s  %s"
              % (f["file"], f["source"], f["sha256"], f["path"]))
    for w in conf["weakened"]:
        print("            WEAKENED  %s (user overlay)" % w)
    if conf["strengthened"]:
        print("            %d additions from the user overlay"
              % len(conf["strengthened"]))
    for n in conf["notes"]:
        print("            note      %s" % n)
    if conf["web_accounts_exposed"]:
        print("            WARNING   web_accounts.yaml is readable by other "
              "users - chmod 600 it")
    print("  config    %s" % conf["config_dir"])
    print("  logs      %s" % conf["log_dir"])
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

    if conf["weakened"]:
        bus.notify("rules.weakened", "Protection removed by user config",
                   "The keywords overlay removes shipped protection: %s."
                   % "; ".join(conf["weakened"]), severity="warning",
                   files=conf["files"])

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
