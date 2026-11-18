"""
Subagent framework - the on-prem org chart.

Roster lives in agents/roster.yaml. Each subagent declares a model, a role, and
a latency budget; the framework enforces the budget and degrades safely when a
model is missing or slow.

THE SAFETY INVARIANT
--------------------
A subagent may only ADD protection, never remove it. `Sentry.scan()` returns
*additional* matches to union into the deterministic result. There is no code
path in which a model's output clears a match that router/rules.py found, and
no subagent is consulted when deciding that something MAY leave. Models advise;
hooks decide. Every failure mode - model absent, timeout, malformed output -
degrades to "deterministic gate alone", which is stricter, never looser.
"""

import json
import math
import os
import re
import time
import urllib.error
import urllib.request

import yaml

from bus import notifications as bus
from router.rules import Match

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ROSTER_PATH = os.path.join(BASE, "agents", "roster.yaml")
ENDPOINT = "http://localhost:11434"


def load_roster() -> dict:
    with open(ROSTER_PATH, "r", encoding="utf-8") as fh:
        return yaml.safe_load(fh) or {}


def _post(path: str, body: dict, timeout: float):
    req = urllib.request.Request(ENDPOINT + path, data=json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json"})
    return json.load(urllib.request.urlopen(req, timeout=timeout))


def ngrams(text: str, max_words: int = 4):
    words = text.split()
    out = []
    for k in range(1, max_words + 1):
        out += [" ".join(words[i:i + k]) for i in range(len(words) - k + 1)]
    return out


# Words that are generic in any codebase. If a gram and a protected term have
# ONLY these in common, their embedding similarity is an artefact of shared
# vocabulary rather than shared meaning - "list comprehension" scores 0.63
# against "customer list" purely on the word "list". A threshold cannot
# separate that case (it sits between two genuine paraphrases at 0.58 and
# 0.64), so it is vetoed structurally instead.
GENERIC = {
    "list", "lists", "set", "sets", "map", "maps", "dict", "array", "arrays",
    "string", "strings", "number", "numbers", "item", "items", "object",
    "objects", "value", "values", "key", "keys", "data", "type", "types",
    "file", "files", "line", "lines", "loop", "loops", "index", "table",
    "record", "records", "field", "fields", "name", "names", "code", "test",
    "tests", "config", "log", "logs", "user", "users", "internal", "model",
    "models", "engine", "engines", "system", "systems", "service", "base",
}


def _stem(w: str) -> str:
    w = re.sub(r"[^a-z0-9]+", "", w.lower())
    for suf in ("tion", "ing", "ies", "ed", "es", "s"):
        if len(w) > 4 and w.endswith(suf):
            return w[: -len(suf)]
    return w


def _stems(text: str) -> set:
    return {_stem(w) for w in text.split() if w}


def generic_only_overlap(gram: str, term: str) -> bool:
    """True if the only words these two share are generic vocabulary."""
    shared = _stems(gram) & _stems(term)
    if not shared:
        return False                      # no lexical overlap: a real paraphrase
    return all(w in {_stem(g) for g in GENERIC} for w in shared)


def cosine(a, b) -> float:
    num = sum(x * y for x, y in zip(a, b))
    da = math.sqrt(sum(x * x for x in a))
    db = math.sqrt(sum(y * y for y in b))
    return num / (da * db) if da and db else 0.0


# ---------------------------------------------------------------------------

class Subagent:
    """Base: identity, budget, and a health check that never raises."""

    def __init__(self, spec: dict):
        self.spec = spec
        self.id = spec["id"]
        self.role = spec["role"]
        self.tier = spec["tier"]
        self.model = spec["model"]
        self.budget_ms = spec.get("budget_ms", 2000)
        self.enabled = spec.get("enabled", True)
        self.available = None       # tri-state: None = not yet probed

    def probe(self) -> bool:
        if not self.enabled or self.spec.get("backend") == "simulated":
            self.available = False
            return False
        try:
            data = _post("/api/tags", {}, 3) if False else json.load(
                urllib.request.urlopen(ENDPOINT + "/api/tags", timeout=3))
            names = [m["name"] for m in data.get("models", [])]
            self.available = self.model in names
        except (urllib.error.URLError, OSError, ValueError, KeyError):
            self.available = False
        return self.available

    def status(self) -> dict:
        return {"id": self.id, "role": self.role, "tier": self.tier,
                "model": self.model, "enabled": self.enabled,
                "available": self.available,
                "budget_ms": self.budget_ms,
                "size_mb": self.spec.get("size_mb"),
                "description": (self.spec.get("description") or "").strip()}


class Sentry(Subagent):
    """
    Tier 0 - semantic gate.

    Catches protected concepts that were re-worded rather than typed. Only ever
    ADDS matches. If it is unavailable or over budget it contributes nothing,
    and the deterministic gate stands alone.
    """

    def __init__(self, spec):
        super().__init__(spec)
        self.threshold = float(spec.get("threshold", 0.5))
        self.generic_threshold = float(spec.get("generic_overlap_threshold", 0.75))
        self._term_vecs = None
        self._term_sig = None

    def _embed(self, texts, timeout_s):
        d = _post("/api/embed",
                  {"model": self.model, "input": texts, "keep_alive": "60m"},
                  timeout_s)
        return d["embeddings"]

    def warm(self, terms):
        """Embed the protected-term list once. Cached against the term set."""
        sig = tuple(terms)
        if self._term_sig == sig and self._term_vecs:
            return True
        if not self.probe():
            return False
        try:
            self._term_vecs = self._embed(list(terms), 30)
            self._term_sig = sig
            return True
        except (urllib.error.URLError, OSError, ValueError, KeyError):
            self._term_vecs = None
            return False

    def scan(self, prompt: str, terms, term_meta: dict, task_id: str = ""):
        """
        Returns ADDITIONAL matches only. Never returns a verdict, never clears
        an existing match, and returns [] on any failure.
        """
        if not self.enabled or not prompt.strip():
            return []
        if not self.warm(terms):
            return []

        started = time.time()
        grams = ngrams(prompt, 4)
        if not grams:
            return []
        try:
            gvecs = self._embed(grams, self.budget_ms / 1000.0 * 4)
        except (urllib.error.URLError, OSError, ValueError, KeyError):
            return []

        elapsed_ms = (time.time() - started) * 1000
        if elapsed_ms > self.budget_ms:
            # Over budget: report it, contribute nothing. Never block a prompt
            # on an advisory model.
            bus.emit("subagent", task_id=task_id, agent=self.id,
                     outcome="over_budget", ms=round(elapsed_ms))
            return []

        best = {}
        for gv, gram in zip(gvecs, grams):
            for tv, term in zip(self._term_vecs, terms):
                score = cosine(gv, tv)
                # A match resting only on generic shared vocabulary must clear
                # a much higher bar before it is believed.
                bar = (self.generic_threshold
                       if generic_only_overlap(gram, term) else self.threshold)
                if score >= bar and score < 0.999:
                    prev = best.get(term)
                    if not prev or score > prev[0]:
                        best[term] = (score, gram)

        out = []
        for term, (score, gram) in best.items():
            meta = term_meta.get(term, {})
            out.append(Match(
                term=term, group=meta.get("group", "semantic"),
                label=meta.get("label", "Protected (semantic match)"),
                severity=meta.get("severity", "high"),
                where="prompt:semantic",
                excerpt="%r reads as %r (similarity %.2f)" % (gram, term, score),
                exact=False, score=round(score, 3)))

        bus.emit("subagent", task_id=task_id, agent=self.id, outcome="scanned",
                 ms=round(elapsed_ms), grams=len(grams), added=len(out))
        return out


class Clerk(Subagent):
    """Tier 1 - task triage into the task.schema.json type enum."""

    TYPES = ["code.generate", "code.review", "code.fix", "docs.write",
             "docs.summarize", "data.transform", "qa.answer", "security.audit",
             "ops.task", "other"]

    PROMPT = ("Classify this developer request into exactly one label from "
              "this list:\n%s\n\nRequest: %s\n\nReply with only the label.")

    def classify(self, prompt: str, task_id: str = "") -> dict:
        if not self.enabled or not self.probe():
            return {"type": "other", "by": "default", "ms": 0}
        started = time.time()
        try:
            d = _post("/api/generate", {
                "model": self.model,
                "prompt": self.PROMPT % ("\n".join(self.TYPES), prompt),
                "stream": False, "keep_alive": "60m",
                # qwen3 is a reasoning model: with thinking enabled Ollama puts
                # the chain-of-thought in a separate `thinking` field and leaves
                # `response` empty until it finishes - which a 24-token budget
                # never reaches, so every answer came back "other". Triage is a
                # labelling job; it does not want deliberation.
                "think": False,
                "options": {"num_predict": 24, "temperature": 0.0},
            }, self.budget_ms / 1000.0 * 3)
        except (urllib.error.URLError, OSError, ValueError, KeyError):
            return {"type": "other", "by": "unavailable", "ms": 0}

        ms = (time.time() - started) * 1000
        text = (d.get("response") or "").strip().lower()
        # Longest label first, so "code.review" is not shadowed by a prefix.
        found = next((t for t in sorted(self.TYPES, key=len, reverse=True)
                      if t in text), "other")
        bus.emit("subagent", task_id=task_id, agent=self.id, outcome="classified",
                 ms=round(ms), task_type=found)
        return {"type": found, "by": self.id, "ms": round(ms)}


# ---------------------------------------------------------------------------

CLASSES = {"semantic-gate": Sentry, "triage": Clerk}


class Org:
    """The roster, instantiated. Unknown roles become inert base Subagents."""

    def __init__(self):
        self.cfg = load_roster()
        self.agents = {}
        for spec in self.cfg.get("roster", []):
            cls = CLASSES.get(spec.get("role"), Subagent)
            self.agents[spec["id"]] = cls(spec)
        self.typo_gate = self.cfg.get("typo_gate", {})

    def get(self, agent_id: str):
        return self.agents.get(agent_id)

    def status(self):
        for a in self.agents.values():
            a.probe()
        return {"agents": [a.status() for a in
                           sorted(self.agents.values(), key=lambda x: x.tier)],
                "typo_gate": self.typo_gate}
