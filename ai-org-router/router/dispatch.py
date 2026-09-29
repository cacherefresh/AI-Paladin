"""
Dispatcher: turns a Classification + mode into a routing decision.

The decision object is what the UI renders and what the audit log keeps.
Nothing here talks to a model; it only decides who gets to.
"""

import uuid
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from typing import Dict, List, Optional

from router.classifier import (Classification, Config, minimal_slice,
                               rank_relevant_files)


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class Decision:
    task_id: str
    tier: str                       # 'local' | 'escalated'
    target: str                     # 'onprem' | 'bigai'
    reason: str
    locked: bool                    # invariant fired - user cannot override
    mode: str
    severity: str
    classification: dict
    requires_confirmation: bool = False
    requires_disclosure: bool = False
    egress_payload: str = "none"    # 'none' | 'full' | 'minimal'
    staged: dict = field(default_factory=dict)
    escalation_offered: bool = False
    sealed: bool = False        # decided under a posture with no egress path
    posture: str = ""           # mode.posture, e.g. 'sealed'
    withheld_bytes: int = 0     # what WOULD have left, had the gate not fired
    created_at: str = field(default_factory=now_iso)

    def to_dict(self):
        return asdict(self)


def decide(prompt: str, mode_id: str, cfg: Config, corpus_id: str = "alpha-ip",
           user_requested_escalation: bool = False) -> Decision:
    """
    Order of operations matters and is the point of the product:

      1. classify the prompt      (no network)
      2. apply the invariant      (no network)
      3. apply the posture        (no network)
      4. only then consider mode  (may open a socket)
    """
    mode = cfg.modes.get(mode_id) or cfg.modes.get("slow")
    task_id = "task-" + uuid.uuid4().hex[:10]
    # A sealed posture is a property of the mode, not of its id, so a future
    # LAN-scoped posture inherits this path without touching the dispatcher.
    sealed = bool(mode.get("seal_egress"))

    # --- Step 1: what would travel with this prompt? -----------------------
    # Rank first, so protected files are caught even if the prompt is clean.
    candidates = rank_relevant_files(prompt, corpus_id)
    candidate_paths = [c["path"] for c in candidates]

    # --- Step 2: classify prompt + staged content --------------------------
    from router.classifier import classify
    cls = classify(prompt, cfg, corpus_id, staged_files=candidate_paths)

    # --- Step 3: THE INVARIANT ---------------------------------------------
    if cls.matched:
        terms = sorted({m.term for m in cls.matches})[:4]
        # Quantify the save: the payload this task would have carried out if
        # the invariant had not fired. This is the ledger's protection figure.
        withheld = len(prompt.encode("utf-8")) + sum(c["bytes"] for c in candidates)
        return Decision(
            withheld_bytes=withheld,
            task_id=task_id,
            tier="local",
            target="onprem",
            reason=("Protected IP detected (%s) - pinned to on-prem by "
                    "rules engine. Not overridable." %
                    ", ".join(repr(t) for t in terms)),
            locked=True,
            sealed=sealed,
            posture=mode.get("posture", ""),
            mode=mode["id"],
            severity=cls.severity,
            classification=cls.to_dict(),
            requires_confirmation=False,
            egress_payload="none",
        )

    # --- Step 4: THE POSTURE -----------------------------------------------
    # No protected-IP match, so the gate has nothing to say. Under a sealed
    # posture that does not matter: there is no destination to route to. The
    # request to escalate is not refused here so much as unanswerable - the
    # egress guard has already removed the socket.
    if sealed:
        withheld = len(prompt.encode("utf-8")) + sum(c["bytes"] for c in candidates)
        reason = ("Posture '%s' is sealed: no destination outside this machine "
                  "is reachable. Executed on-prem." % mode["id"])
        if user_requested_escalation:
            reason = ("Escalation requested, but posture '%s' is sealed - the "
                      "egress guard refuses every non-loopback destination. "
                      "Executed on-prem." % mode["id"])
        return Decision(
            withheld_bytes=withheld,
            task_id=task_id,
            tier="local",
            target="onprem",
            reason=reason,
            locked=True,
            sealed=True,
            posture=mode.get("posture", "sealed"),
            mode=mode["id"],
            severity=cls.severity,
            classification=cls.to_dict(),
            requires_confirmation=False,
            escalation_offered=False,
            egress_payload="none",
        )

    # --- Step 5: no match, open posture. The mode decides. -----------------
    destination = mode.get("on_no_match", "onprem")

    if destination == "onprem" and not user_requested_escalation:
        return Decision(
            task_id=task_id,
            tier="local",
            target="onprem",
            reason=("No protected-IP match, but mode '%s' prefers on-prem for "
                    "all traffic." % mode["id"]),
            locked=False,
            mode=mode["id"],
            severity="info",
            classification=cls.to_dict(),
            escalation_offered=bool(mode.get("allow_escalation_offer")),
            egress_payload="none",
        )

    # --- Step 6: this is leaving the building. Stage and disclose. ---------
    payload_kind = mode.get("egress_payload", "full")
    staged: Dict = {"kind": payload_kind, "prompt": prompt,
                    "prompt_bytes": len(prompt.encode("utf-8")), "files": []}

    if payload_kind == "minimal":
        # superfast-risky: one file, one window of lines.
        if candidates:
            sl = minimal_slice(corpus_id, candidates[0]["path"], prompt)
            staged["files"] = [sl]
            staged["reduction_note"] = (
                "%d of %d bytes of %s (%.0f%% withheld)" % (
                    sl["bytes"], sl["full_bytes"], sl["path"],
                    100.0 * (1 - sl["bytes"] / max(1, sl["full_bytes"]))))
    elif payload_kind == "full":
        from router.classifier import read_corpus_file
        for c in candidates[:4]:
            content = read_corpus_file(corpus_id, c["path"])
            staged["files"].append({
                "path": c["path"],
                "start_line": 1,
                "end_line": content.count("\n") + 1,
                "text": content,
                "bytes": len(content.encode("utf-8")),
                "full_bytes": len(content.encode("utf-8")),
            })

    staged["total_bytes"] = (staged["prompt_bytes"]
                             + sum(f["bytes"] for f in staged["files"]))

    reason = ("No protected-IP match. Mode '%s' routes non-matching work to "
              "BIG-AI." % mode["id"])
    if user_requested_escalation:
        reason = "Human explicitly requested escalation to BIG-AI."

    return Decision(
        task_id=task_id,
        tier="escalated",
        target="bigai",
        reason=reason,
        locked=False,
        mode=mode["id"],
        severity="info",
        classification=cls.to_dict(),
        requires_confirmation=bool(mode.get("require_confirmation_on_egress", True)),
        requires_disclosure=bool(mode.get("require_full_disclosure")),
        egress_payload=payload_kind,
        staged=staged,
    )
