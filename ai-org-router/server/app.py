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
"""

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
    try:
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

        # --- dry run. No model touched, no socket opened. ----------------
        if p == "/api/classify":
            prompt = (data.get("prompt") or "").strip()
            if not prompt:
                return self._send(400, {"error": "empty prompt"})
            decision = dispatch.decide(
                prompt, data.get("mode", "slow"), CFG,
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

            if d["locked"]:
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


def main():
    health = onprem_health()
    print("\n  AI-Paladin router demo")
    print("  " + "-" * 52)
    print("  on-prem   dev-mistral-2 (%s)" % CFG.nodes["onprem"]["ollama_model"])
    print("            %s" % ("ONLINE" if health["online"] else
                              "OFFLINE - start ollama"))
    print("  BIG-AI    SIMULATED (no ANTHROPIC_API_KEY on this node)")
    print("  rules     %d protected terms, %d protected paths"
          % (CFG.term_count(), len(CFG.protected_paths)))
    print("  " + "-" * 52)
    print("  http://localhost:%d\n" % PORT)

    threading.Thread(target=prewarm, daemon=True).start()
    bus.notify("routing.local", "AI-Paladin router online",
               "Invariant active: protected-IP keyword match pins execution to "
               "on-prem in every mode.", severity="info")

    ThreadingHTTPServer(("127.0.0.1", PORT), Handler).serve_forever()


if __name__ == "__main__":
    main()
