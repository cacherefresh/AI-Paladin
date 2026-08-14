"""
Notification bus - mockup of a queue/topic system.

In-memory fan-out with a monotonic sequence number, plus an append-only JSONL
sink so the audit trail survives the process. Clients poll ?since=<seq>.

Deliberately a mockup: swapping this for NATS / Kafka / Redis Streams is an
adapter change, not a redesign. What matters for the demo is that every
routing decision and every egress event lands on a topic a human can watch.
"""

import json
import os
import threading
import uuid
from collections import deque
from datetime import datetime, timezone

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SINK = os.path.join(BASE, "logs", "notifications.jsonl")
EVENT_SINK = os.path.join(BASE, "logs", "events.jsonl")

_lock = threading.Lock()
_seq = 0
_events = deque(maxlen=4000)        # token/status stream, per task
_notifications = deque(maxlen=500)  # human-facing, needs attention


def _next_seq() -> int:
    global _seq
    _seq += 1
    return _seq


def _append(path: str, record: dict):
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(record) + "\n")
    except OSError:
        pass  # never let the audit sink break the demo


def emit(kind: str, task_id: str = "", **payload) -> dict:
    """
    Low-volume, high-frequency stream event (tokens, phase changes, timings).
    Written to logs/events.jsonl, shaped after schemas/event.schema.json.
    """
    with _lock:
        rec = {
            "seq": _next_seq(),
            "id": "evt-" + uuid.uuid4().hex[:8],
            "ts": datetime.now(timezone.utc).isoformat(),
            "kind": kind,
            "task_id": task_id,
            **payload,
        }
        _events.append(rec)
    if kind not in ("token",):          # tokens would drown the audit file
        _append(EVENT_SINK, rec)
    return rec


def notify(topic: str, title: str, body: str = "", severity: str = "info",
           task_id: str = "", **extra) -> dict:
    """
    Human-facing notification on a topic. This is what the notification
    screen renders and what makes an unread badge light up.
    """
    with _lock:
        rec = {
            "seq": _next_seq(),
            "id": "ntf-" + uuid.uuid4().hex[:8],
            "ts": datetime.now(timezone.utc).isoformat(),
            "kind": "notification",
            "topic": topic,
            "title": title,
            "body": body,
            "severity": severity,
            "task_id": task_id,
            "read": False,
            **extra,
        }
        _notifications.append(rec)
        _events.append(rec)
    _append(SINK, rec)
    return rec


def since(seq: int = 0, limit: int = 800) -> list:
    with _lock:
        return [e for e in _events if e["seq"] > seq][-limit:]


def notifications(unread_only: bool = False) -> list:
    with _lock:
        items = list(_notifications)
    if unread_only:
        items = [n for n in items if not n.get("read")]
    return list(reversed(items))


def mark_all_read():
    with _lock:
        for n in _notifications:
            n["read"] = True


def current_seq() -> int:
    with _lock:
        return _seq
