"""
Rules engine.

MVP (enforced tonight): exact, case-insensitive substring matching on a
keyword list, plus glob matching on protected paths.

NON-MVP (declared, not enforced): boolean composition and inexact matching.
The shape is defined here so the roadmap is legible in code and on screen,
but evaluate_boolean() is never reached while the roadmap flag is off.
"""

import fnmatch
import re
from dataclasses import dataclass, field, asdict
from typing import List, Optional


@dataclass
class Match:
    """One piece of evidence that a protected term was found."""
    term: str
    group: str
    label: str
    severity: str
    where: str          # 'prompt' | 'file:<path>' | 'path:<path>'
    excerpt: str = ""   # surrounding text, for the audit panel
    exact: bool = True
    score: float = 1.0

    def to_dict(self):
        return asdict(self)


# ---------------------------------------------------------------------------
# MVP matching
# ---------------------------------------------------------------------------

def _excerpt(haystack: str, start: int, end: int, pad: int = 45) -> str:
    lo = max(0, start - pad)
    hi = min(len(haystack), end + pad)
    snippet = haystack[lo:hi].replace("\n", " ").strip()
    return ("..." if lo > 0 else "") + snippet + ("..." if hi < len(haystack) else "")


def scan_text(text: str, groups: List[dict], where: str) -> List[Match]:
    """Find every protected term present in `text`. Case-insensitive."""
    if not text:
        return []
    hay = text.lower()
    found: List[Match] = []
    seen = set()

    for group in groups:
        gid = group.get("group", "ungrouped")
        label = group.get("label", gid)
        severity = group.get("severity", "medium")

        for term in group.get("terms", []):
            t = str(term).lower()
            if not t:
                continue
            # Word-ish boundary so "pii" doesn't fire inside "happiness".
            pattern = re.escape(t)
            if t.isalnum():
                pattern = r"\b" + pattern + r"\b"
            m = re.search(pattern, hay)
            if not m:
                continue
            key = (t, where)
            if key in seen:
                continue
            seen.add(key)
            found.append(Match(
                term=term,
                group=gid,
                label=label,
                severity=severity,
                where=where,
                excerpt=_excerpt(text, m.start(), m.end()),
            ))
    return found


def scan_path(path: str, protected_paths: List[str]) -> Optional[Match]:
    """A file can be protected by location alone, whatever is inside it."""
    for glob in protected_paths:
        if fnmatch.fnmatch(path, glob) or fnmatch.fnmatch("/" + path.lstrip("/"), glob):
            return Match(
                term=glob,
                group="protected-path",
                label="Protected Path",
                severity="critical",
                where="path:" + path,
                excerpt=path,
            )
    return None


SEVERITY_ORDER = {"info": 0, "low": 1, "medium": 2, "high": 3, "critical": 4}


def worst_severity(matches: List[Match]) -> str:
    if not matches:
        return "info"
    return max((m.severity for m in matches), key=lambda s: SEVERITY_ORDER.get(s, 0))


# ---------------------------------------------------------------------------
# Near-miss gate: deterministic, no model involved.
#
# Embeddings are poor at character-level corruption ("pricng engnie" scores
# only ~0.50 against "pricing engine"), so typo evasion is caught here with
# arithmetic instead. ADDITIVE ONLY - this can raise a match the exact matcher
# missed; it can never clear one.
# ---------------------------------------------------------------------------

def _grams(text: str, max_words: int):
    words = text.split()
    out = []
    for k in range(1, max_words + 1):
        out += [" ".join(words[i:i + k]) for i in range(len(words) - k + 1)]
    return out


def scan_near_miss(text: str, groups: List[dict], already: set,
                   min_similarity: float = 0.85,
                   max_gram_words: int = 4) -> List[Match]:
    """
    Flag terms that are ALMOST present - a misspelling, a transposition, a
    dropped letter. `already` is the set of terms the exact pass matched, so a
    term is never reported twice.
    """
    if not text:
        return []
    grams = _grams(text.lower(), max_gram_words)
    found, seen = [], set()

    for group in groups:
        for term in group.get("terms", []):
            t = str(term).lower()
            if not t or term in already or term in seen:
                continue
            width = len(t.split())
            best_score, best_gram = 0.0, ""
            for g in grams:
                # only compare like-for-like word counts; cheap and precise
                if abs(len(g.split()) - width) > 0:
                    continue
                sc = fuzzy_score(g, t)
                if sc > best_score:
                    best_score, best_gram = sc, g
            if min_similarity <= best_score < 1.0:
                seen.add(term)
                found.append(Match(
                    term=term, group=group.get("group", "ungrouped"),
                    label=group.get("label", ""),
                    severity=group.get("severity", "medium"),
                    where="prompt:near-miss",
                    excerpt="%r is %.0f%% match for %r - possible evasion"
                            % (best_gram, 100 * best_score, term),
                    exact=False, score=round(best_score, 3)))
    return found


# ---------------------------------------------------------------------------
# NON-MVP - roadmap only. Present so the interface is visible; not wired up.
# ---------------------------------------------------------------------------

def evaluate_boolean(rule: dict, text: str) -> bool:
    """
    Boolean rule composition: must_contain / cannot_contain / any / all /
    and / or / not.

    NOT ENFORCED IN MVP. router/keywords.yaml ships with
    rules_engine_roadmap.enabled: false, and the classifier never calls this.
    """
    raise NotImplementedError("Boolean rules engine is a post-MVP goal.")


def fuzzy_score(a: str, b: str) -> float:
    """
    Normalised Levenshtein similarity. 1.0 is identical; the gate uses >= 0.85.
    Used by scan_near_miss() above.
    """
    a, b = a.lower(), b.lower()
    if a == b:
        return 1.0
    if not a or not b:
        return 0.0
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb)))
        prev = cur
    return 1.0 - prev[-1] / max(len(a), len(b))
