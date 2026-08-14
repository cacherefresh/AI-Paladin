"""
Classifier: given a prompt and a corpus, decide what is protected and what
would be staged for egress.

This runs BEFORE any network socket is opened. That ordering is the whole
product: the decision is made on the prompt, not by the model handling it.
"""

import fnmatch
import os
import re
from dataclasses import dataclass, field
from typing import Dict, List

import yaml

from router import rules
from router.rules import Match

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# Files we will read from a corpus when staging a payload.
TEXT_EXT = {".py", ".js", ".ts", ".go", ".java", ".rs", ".rb", ".c", ".h",
            ".cpp", ".sql", ".yaml", ".yml", ".json", ".md", ".txt", ".env",
            ".toml", ".ini", ".sh", ".cfg"}
MAX_FILE_BYTES = 200_000
STOPWORDS = {
    # English filler
    "the", "a", "an", "and", "or", "but", "if", "then", "for", "to", "of",
    "in", "on", "is", "are", "was", "be", "this", "that", "it", "with", "as",
    "at", "by", "from", "can", "you", "i", "we", "me", "my", "our", "how",
    "what", "why", "do", "does", "there", "here", "not", "any", "all", "one",
    # Generic engineering vocabulary. These words carry no signal about WHICH
    # file is relevant - every codebase is full of them - and letting them
    # score would drag protected files into unrelated tasks.
    "please", "fix", "help", "need", "want", "bug", "issue", "problem",
    "error", "code", "file", "files", "line", "lines", "function", "func",
    "method", "class", "test", "tests", "add", "update", "change", "make",
    "work", "works", "return", "returns", "value", "values", "name", "type",
    "use", "using", "used", "def", "self", "none", "true", "false", "import",
    "get", "set", "new", "old", "should", "would", "could", "when", "where",
}


def load_yaml(path: str) -> dict:
    with open(path, "r", encoding="utf-8") as fh:
        return yaml.safe_load(fh) or {}


class Config:
    """Hot-reloadable view of keywords.yaml + policy.yaml."""

    def __init__(self):
        self.keywords_path = os.path.join(BASE, "router", "keywords.yaml")
        self.policy_path = os.path.join(BASE, "router", "policy.yaml")
        self.reload()

    def reload(self):
        self.keywords = load_yaml(self.keywords_path)
        self.policy = load_yaml(self.policy_path)
        self.groups = self.keywords.get("protected_terms", [])
        self.protected_paths = self.keywords.get("protected_paths", [])
        self.modes = {m["id"]: m for m in self.policy.get("modes", [])}
        self.nodes = self.policy.get("nodes", {})
        return self

    def term_count(self) -> int:
        return sum(len(g.get("terms", [])) for g in self.groups)


# ---------------------------------------------------------------------------
# Corpus handling
# ---------------------------------------------------------------------------

CORPORA = {
    "alpha-ip": {
        "id": "alpha-ip",
        "label": "Seeded Alpha IP corpus (demo/)",
        "root": os.path.join(BASE, "demo"),
        "safe": True,
    },
    "real-repo": {
        "id": "real-repo",
        "label": "This AI-Paladin working tree (LIVE)",
        "root": os.path.dirname(BASE),
        "safe": False,
    },
}


_EXCLUDE_CACHE = None


def _scan_exclude() -> List[str]:
    global _EXCLUDE_CACHE
    if _EXCLUDE_CACHE is None:
        try:
            kw = load_yaml(os.path.join(BASE, "router", "keywords.yaml"))
            _EXCLUDE_CACHE = kw.get("scan_exclude", []) or []
        except OSError:
            _EXCLUDE_CACHE = []
    return _EXCLUDE_CACHE


def is_excluded(relpath: str) -> bool:
    """The rules files must not trip the rules they define."""
    rel = relpath.replace(os.sep, "/")
    return any(fnmatch.fnmatch(rel, g) or fnmatch.fnmatch("/" + rel, g)
               for g in _scan_exclude())


def list_corpus_files(corpus_id: str) -> List[str]:
    spec = CORPORA.get(corpus_id) or CORPORA["alpha-ip"]
    root = spec["root"]
    out = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames
                       if d not in {".git", "node_modules", "__pycache__",
                                    ".venv", "logs", ".DS_Store"}]
        for fn in filenames:
            if os.path.splitext(fn)[1].lower() not in TEXT_EXT and fn != ".env":
                continue
            full = os.path.join(dirpath, fn)
            try:
                if os.path.getsize(full) > MAX_FILE_BYTES:
                    continue
            except OSError:
                continue
            rel = os.path.relpath(full, root)
            if is_excluded(rel):
                continue
            out.append(rel)
    return sorted(out)


def read_corpus_file(corpus_id: str, relpath: str) -> str:
    spec = CORPORA.get(corpus_id) or CORPORA["alpha-ip"]
    full = os.path.normpath(os.path.join(spec["root"], relpath))
    if not full.startswith(os.path.normpath(spec["root"])):
        return ""  # path traversal guard
    try:
        with open(full, "r", encoding="utf-8", errors="replace") as fh:
            return fh.read(MAX_FILE_BYTES)
    except OSError:
        return ""


def _tokens(text: str) -> set:
    return {w for w in re.findall(r"[a-z0-9_]{3,}", text.lower())
            if w not in STOPWORDS}


_INDEX_CACHE = {}


def _corpus_index(corpus_id: str):
    """
    Build (and cache) a token index over the corpus, with document frequency
    per token. Cached on the file-list signature so edits to demo/ are picked
    up without a restart.
    """
    files = list_corpus_files(corpus_id)
    sig = tuple(files)
    hit = _INDEX_CACHE.get(corpus_id)
    if hit and hit["sig"] == sig:
        return hit

    docs, df = {}, {}
    for rel in files:
        content = read_corpus_file(corpus_id, rel)
        if not content:
            continue
        toks = _tokens(content) | _tokens(rel)
        docs[rel] = {"tokens": toks,
                     "bytes": len(content.encode("utf-8")),
                     "lines": content.count("\n") + 1,
                     "name_tokens": _tokens(rel)}
        for t in toks:
            df[t] = df.get(t, 0) + 1

    idx = {"sig": sig, "docs": docs, "df": df, "n": max(1, len(docs))}
    _INDEX_CACHE[corpus_id] = idx
    return idx


def rank_relevant_files(prompt: str, corpus_id: str, limit: int = 4,
                        min_score: float = 0.30) -> List[dict]:
    """
    Which files would a coding agent actually pull in to answer this prompt?

    Scored by inverse document frequency, not raw overlap. A token appearing
    in most files ("bug", "price", "return") carries almost no weight; a token
    appearing in one file ("business_days_between", "scoring_kernel") carries
    a lot. Filename hits are weighted 2x, because that is how engineers and
    coding agents actually navigate a repo.

    This threshold matters for correctness, not just relevance: everything
    ranked here gets classified, so a sloppy ranker would drag protected files
    into unrelated tasks and pin clean work on-prem for no reason.
    """
    import math

    idx = _corpus_index(corpus_id)
    want = _tokens(prompt)
    if not want:
        return []

    n = idx["n"]
    weights = {t: math.log(1 + n / (1 + idx["df"].get(t, 0))) for t in want}
    total_w = sum(weights.values()) or 1.0

    scored = []
    for rel, doc in idx["docs"].items():
        overlap = want & doc["tokens"]
        if len(overlap) < 2:          # a single token is coincidence, not relevance
            continue
        raw = sum(weights[t] for t in overlap)
        raw += sum(weights[t] for t in (want & doc["name_tokens"]))  # 2x filename
        score = raw / total_w
        if score < min_score:
            continue
        scored.append({
            "path": rel,
            "score": round(score, 3),
            "bytes": doc["bytes"],
            "lines": doc["lines"],
            "matched_tokens": sorted(overlap, key=lambda t: -weights[t])[:8],
        })

    scored.sort(key=lambda d: -d["score"])
    return scored[:limit]


DEF_RE = re.compile(
    r"^\s*(?:async\s+)?(?:def|class|function|func|fn|public|private|"
    r"protected|static|export)\b|^\s*(?:const|let|var)\s+\w+\s*=\s*"
    r"(?:async\s*)?\(?[\w\s,]*\)?\s*=>")


def _blocks(lines):
    """Split a source file into definition-bounded blocks."""
    starts = [i for i, ln in enumerate(lines) if DEF_RE.match(ln)]
    if not starts:
        return []
    if starts[0] > 0:
        starts = [0] + starts
    out = []
    for n, s in enumerate(starts):
        e = starts[n + 1] if n + 1 < len(starts) else len(lines)
        out.append((s, e))
    return out


def minimal_slice(corpus_id: str, relpath: str, prompt: str,
                  max_lines: int = 24) -> dict:
    """
    superfast-risky payload builder: the smallest coherent slice of a file
    that is plausibly enough to fix a small bug.

    Snaps to definition boundaries rather than an arbitrary line window - a
    half function is useless to the model and unreadable in the disclosure
    window. A definition whose NAME appears in the prompt wins outright;
    that is the strongest available signal about which function is meant.
    """
    content = read_corpus_file(corpus_id, relpath)
    lines = content.split("\n")
    want = _tokens(prompt)

    best, best_score = None, -1.0
    for (s, e) in _blocks(lines):
        block = lines[s:e]
        overlap = want & _tokens(" ".join(block))
        score = float(len(overlap))
        # The definition's own name is worth more than its body.
        m = re.search(r"\b(?:def|class|function|func|const|let|var)\s+(\w+)",
                      lines[s])
        if m and m.group(1).lower() in want:
            score += 10.0
        # Prefer tight blocks when scores are otherwise equal.
        score -= 0.01 * len(block)
        if score > best_score:
            best_score, best = score, (s, e)

    if best is None:                     # no definitions - fall back to head
        s, e = 0, min(len(lines), max_lines)
    else:
        s, e = best
        if e - s > max_lines:
            e = s + max_lines

    slice_text = "\n".join(lines[s:e]).rstrip()
    return {
        "path": relpath,
        "start_line": s + 1,
        "end_line": e,
        "text": slice_text,
        "bytes": len(slice_text.encode("utf-8")),
        "full_bytes": len(content.encode("utf-8")),
    }


# ---------------------------------------------------------------------------
# Classification
# ---------------------------------------------------------------------------

@dataclass
class Classification:
    matched: bool
    matches: List[Match] = field(default_factory=list)
    severity: str = "info"
    scanned_prompt: bool = True
    scanned_files: List[str] = field(default_factory=list)

    def to_dict(self):
        return {
            "matched": self.matched,
            "severity": self.severity,
            "matches": [m.to_dict() for m in self.matches],
            "scanned_files": self.scanned_files,
            "match_count": len(self.matches),
        }


_ORG = None


def _org():
    """Lazy so importing the router never requires the subagent stack."""
    global _ORG
    if _ORG is None:
        try:
            from nodes.subagents import Org
            _ORG = Org()
        except Exception:
            _ORG = False
    return _ORG or None


def classify(prompt: str, cfg: Config, corpus_id: str = "alpha-ip",
             staged_files: List[str] = None, task_id: str = "") -> Classification:
    """
    Scan the prompt, and the contents of anything staged to travel with it.
    A clean prompt that drags a protected file along is still protected.
    """
    matches: List[Match] = list(rules.scan_text(prompt, cfg.groups, "prompt"))
    scanned: List[str] = []

    for rel in (staged_files or []):
        scanned.append(rel)
        path_hit = rules.scan_path(rel, cfg.protected_paths)
        if path_hit:
            matches.append(path_hit)
        content = read_corpus_file(corpus_id, rel)
        matches.extend(rules.scan_text(content, cfg.groups, "file:" + rel))

    # --- advisory layers -------------------------------------------------
    # Both are ADDITIVE ONLY. They union extra matches onto the deterministic
    # result; neither can clear a match, and any failure leaves the
    # deterministic verdict untouched. A model never decides that something is
    # safe to send - only that something else looks unsafe.
    already = {m.term for m in matches}
    org = _org()

    if org:
        tg = org.typo_gate or {}
        if tg.get("enabled"):
            matches += rules.scan_near_miss(
                prompt, cfg.groups, already,
                min_similarity=float(tg.get("min_similarity", 0.85)),
                max_gram_words=int(tg.get("max_gram_words", 4)))
            already = {m.term for m in matches}

        sentry = org.get("sentry")
        if sentry and sentry.enabled:
            term_meta, all_terms = {}, []
            for g in cfg.groups:
                for t in g.get("terms", []):
                    all_terms.append(t)
                    term_meta[t] = {"group": g.get("group"), "label": g.get("label"),
                                    "severity": g.get("severity")}
            for m in sentry.scan(prompt, all_terms, term_meta, task_id):
                if m.term not in already:
                    matches.append(m)
                    already.add(m.term)

    return Classification(
        matched=bool(matches),
        matches=matches,
        severity=rules.worst_severity(matches),
        scanned_files=scanned,
    )
