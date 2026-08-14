"""
The ledger: what BIG-AI cost us, and what the gate kept home.

Two questions an executive actually asks, tracked from the first prompt:

  1. What are we spending outside?   -> tokens sent to and returned from BIG-AI
  2. What did we keep inside?        -> tasks pinned, terms fired, bytes withheld

Both are derived from records the router already produces, so nothing here
needs new instrumentation in the hot path. Counters are process-lifetime and
also appended to logs/metrics.jsonl so a session survives a restart for audit.
"""

import json
import os
import threading
from datetime import datetime, timezone

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SINK = os.path.join(BASE, "logs", "metrics.jsonl")

_lock = threading.Lock()

_M = {
    # ---- intellectual property protection -----------------------------
    "tasks_total": 0,
    "tasks_pinned": 0,          # invariant fired: protected IP, on-prem, locked
    "tasks_local": 0,           # ran on-prem for any reason
    "tasks_escalated": 0,       # actually went to BIG-AI
    "egress_denied": 0,         # human refused at the gate
    "egress_blocked": 0,        # policy refused (e.g. outbound net)
    "terms_fired": 0,           # total protected-term hits
    "unique_terms": [],         # which distinct terms have ever fired
    "bytes_withheld_by_gate": 0,      # would have left, but the task was pinned
    "bytes_withheld_by_minimisation": 0,  # cut from staged files before sending
    "bytes_withheld_by_denial": 0,    # staged, then refused by a human
    "bytes_egressed": 0,        # actually left the network

    # ---- BIG-AI consumption -------------------------------------------
    "bigai_calls": 0,
    "bigai_tokens_in": 0,
    "bigai_tokens_out": 0,
    "bigai_seconds": 0.0,
    "bigai_estimated": True,    # true while the leg is simulated

    # ---- on-prem work done instead -------------------------------------
    "onprem_calls": 0,
    "onprem_tokens_in": 0,
    "onprem_tokens_out": 0,
    "onprem_seconds": 0.0,

    "started_at": datetime.now(timezone.utc).isoformat(),
}


def _append(record):
    try:
        os.makedirs(os.path.dirname(SINK), exist_ok=True)
        with open(SINK, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(record) + "\n")
    except OSError:
        pass


def record_decision(decision: dict):
    """Called once per routing decision, before anything executes."""
    with _lock:
        _M["tasks_total"] += 1
        if decision.get("locked"):
            _M["tasks_pinned"] += 1
            _M["bytes_withheld_by_gate"] += decision.get("withheld_bytes", 0)
            matches = decision.get("classification", {}).get("matches", [])
            _M["terms_fired"] += len(matches)
            for m in matches:
                if m["term"] not in _M["unique_terms"]:
                    _M["unique_terms"].append(m["term"])
    _append({"ts": datetime.now(timezone.utc).isoformat(), "kind": "decision",
             "task_id": decision.get("task_id"), "target": decision.get("target"),
             "locked": decision.get("locked"),
             "withheld_bytes": decision.get("withheld_bytes", 0)})


def record_egress(staged: dict, approved: bool, task_id: str = ""):
    """Called when a human resolves the egress gate."""
    total = staged.get("total_bytes", 0)
    saved = sum(max(0, f.get("full_bytes", 0) - f.get("bytes", 0))
                for f in staged.get("files", []))
    with _lock:
        if approved:
            _M["tasks_escalated"] += 1
            _M["bytes_egressed"] += total
            _M["bytes_withheld_by_minimisation"] += saved
        else:
            _M["egress_denied"] += 1
            _M["bytes_withheld_by_denial"] += total
    _append({"ts": datetime.now(timezone.utc).isoformat(), "kind": "egress",
             "task_id": task_id, "approved": approved, "bytes": total,
             "minimised_away": saved})


def record_block():
    with _lock:
        _M["egress_blocked"] += 1


def record_usage(source: str, tokens_in: int, tokens_out: int, seconds: float,
                 estimated: bool = False):
    """Called once per completed model call, from the done event."""
    p = "bigai" if source == "bigai" else "onprem"
    with _lock:
        _M[p + "_calls"] += 1
        _M[p + "_tokens_in"] += int(tokens_in or 0)
        _M[p + "_tokens_out"] += int(tokens_out or 0)
        _M[p + "_seconds"] += float(seconds or 0)
        if p == "onprem":
            _M["tasks_local"] += 1
        if p == "bigai":
            _M["bigai_estimated"] = estimated
    _append({"ts": datetime.now(timezone.utc).isoformat(), "kind": "usage",
             "source": source, "tokens_in": tokens_in, "tokens_out": tokens_out,
             "seconds": seconds, "estimated": estimated})


def snapshot(pricing: dict = None) -> dict:
    """Current ledger, plus derived figures the UI and the deck both use."""
    with _lock:
        m = dict(_M)
        m["unique_terms"] = list(_M["unique_terms"])

    m["unique_term_count"] = len(m["unique_terms"])
    m["bytes_withheld_total"] = (m["bytes_withheld_by_gate"]
                                 + m["bytes_withheld_by_minimisation"]
                                 + m["bytes_withheld_by_denial"])

    # Share of everything that could have left which actually did.
    exposed = m["bytes_egressed"] + m["bytes_withheld_total"]
    m["containment_pct"] = round(100.0 * m["bytes_withheld_total"] / exposed, 1) \
        if exposed else 100.0

    m["bigai_tokens_total"] = m["bigai_tokens_in"] + m["bigai_tokens_out"]
    m["onprem_tokens_total"] = m["onprem_tokens_in"] + m["onprem_tokens_out"]
    total_tok = m["bigai_tokens_total"] + m["onprem_tokens_total"]
    m["local_token_share_pct"] = round(100.0 * m["onprem_tokens_total"] / total_tok, 1) \
        if total_tok else 0.0

    # Cost is computed from a rate the operator sets in policy.yaml. We do not
    # ship a vendor price list; an unset rate yields null, not a guess.
    pricing = pricing or {}
    rin, rout = pricing.get("price_per_mtok_in"), pricing.get("price_per_mtok_out")
    if rin is not None and rout is not None:
        m["bigai_cost_usd"] = round(m["bigai_tokens_in"] / 1e6 * float(rin)
                                    + m["bigai_tokens_out"] / 1e6 * float(rout), 4)
        # What the locally-handled tokens would have cost at the same rate.
        m["avoided_cost_usd"] = round(m["onprem_tokens_in"] / 1e6 * float(rin)
                                      + m["onprem_tokens_out"] / 1e6 * float(rout), 4)
        m["pricing_configured"] = True
    else:
        m["bigai_cost_usd"] = None
        m["avoided_cost_usd"] = None
        m["pricing_configured"] = False
    return m
