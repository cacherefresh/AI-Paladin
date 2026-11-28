"""
Shipped defaults plus the user's own settings.

Two rules decide how a user's file combines with the shipped one:

keywords.yaml is an OVERLAY. The user's file never replaces the shipped one;
it lists changes to it:

    groups:          new groups, defined in full
    add_terms:       {group: [terms]}   add to a shipped or new group
    remove_terms:    {group: [terms]}   remove named shipped terms
    remove_groups:   [group, ...]       remove whole shipped groups
    add_paths:       [glob, ...]
    remove_paths:    [glob, ...]

Leaving a term out of the overlay never removes it; only remove_terms or
remove_groups does. Because the overlay holds changes rather than a copy, an
updated shipped default reaches every user on upgrade. Every removal is
reported as WEAKENED - at boot, in the audit log, and in /api/config - so
lowering protection is always visible and attributable to a file.

policy.yaml, roster.yaml, catalog.yaml, commands.yaml, packages.yaml and
behavioral_rules.yaml are REPLACED whole: if the user's
config folder has one, it is used instead of the shipped file. A merge would
let a missing or misspelled key silently change a security setting; a whole
file is one thing to read and one checksum to record.

A malformed overlay raises OverlayError. The router refuses to start rather
than run with protection the user did not intend.
"""

import copy
import hashlib
import os
from typing import Dict, List, Tuple

import yaml

from ai_paladin import paths

# name in the user's config folder -> location of the shipped default
SHIPPED_FILES = {
    "keywords.yaml": ("router", "keywords.yaml"),
    "policy.yaml": ("router", "policy.yaml"),
    "roster.yaml": ("agents", "roster.yaml"),
    "catalog.yaml": ("models", "catalog.yaml"),
    "commands.yaml": ("security", "policies", "commands.yaml"),
    "packages.yaml": ("security", "policies", "packages.yaml"),
    "behavioral_rules.yaml": ("security", "monitors", "behavioral_rules.yaml"),
}
REPLACED_WHOLE = ("policy.yaml", "roster.yaml", "catalog.yaml",
                  "commands.yaml", "packages.yaml", "behavioral_rules.yaml")

OVERLAY_KEYS = {"groups", "add_terms", "remove_terms", "remove_groups",
                "add_paths", "remove_paths"}
SEVERITIES = {"critical", "high", "medium", "low"}


class OverlayError(ValueError):
    """The user's keywords.yaml cannot be applied as written."""


def _load(path: str) -> dict:
    with open(path, "r", encoding="utf-8") as fh:
        data = yaml.safe_load(fh)
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise OverlayError("%s: top level must be a mapping" % path)
    return data


def sha256_short(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        h.update(fh.read())
    return h.hexdigest()[:12]


def resolve(name: str) -> Tuple[str, str]:
    """(path, 'user' | 'shipped') for a whole-file setting."""
    user = paths.user_config(name)
    if name in REPLACED_WHOLE and os.path.isfile(user):
        return user, "user"
    return paths.shipped(*SHIPPED_FILES[name]), "shipped"


def load_whole(name: str) -> Tuple[dict, dict]:
    """Load policy/roster/catalog: the user's copy if present, else shipped."""
    path, source = resolve(name)
    data = _load(path)
    return data, {"file": name, "path": path, "source": source,
                  "sha256": sha256_short(path)}


# ---------------------------------------------------------------------------
# keywords.yaml overlay
# ---------------------------------------------------------------------------

def _str_list(value, where: str) -> List[str]:
    if value is None:
        return []
    if not isinstance(value, list) or not all(isinstance(v, str) for v in value):
        raise OverlayError("%s must be a list of strings" % where)
    return [v.strip() for v in value if v.strip()]


def _group_map(value, where: str) -> Dict[str, List[str]]:
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise OverlayError("%s must map a group id to a list of terms" % where)
    return {str(g): _str_list(t, "%s.%s" % (where, g)) for g, t in value.items()}


def merge_keywords(shipped: dict, overlay: dict) -> Tuple[dict, dict]:
    """
    Apply an overlay to the shipped keywords. Returns (merged, report).
    Pure: neither argument is modified.
    """
    unknown = set(overlay) - OVERLAY_KEYS
    if unknown:
        raise OverlayError(
            "unknown key(s) %s. Allowed: %s"
            % (", ".join(sorted(unknown)), ", ".join(sorted(OVERLAY_KEYS))))

    merged = copy.deepcopy(shipped)
    groups = merged.setdefault("protected_terms", [])
    by_id = {g["group"]: g for g in groups}
    pths = merged.setdefault("protected_paths", [])
    report = {"weakened": [], "strengthened": [], "notes": []}

    for gid in _str_list(overlay.get("remove_groups"), "remove_groups"):
        if gid in by_id:
            n = len(by_id[gid].get("terms", []))
            groups.remove(by_id.pop(gid))
            report["weakened"].append(
                "removed group '%s' (%d terms)" % (gid, n))
        else:
            report["notes"].append("remove_groups: no group '%s'" % gid)

    new_groups = overlay.get("groups") or []
    if not isinstance(new_groups, list):
        raise OverlayError("groups must be a list")
    for i, g in enumerate(new_groups):
        if not isinstance(g, dict) or not isinstance(g.get("group"), str):
            raise OverlayError("groups[%d] needs a 'group' id" % i)
        gid = g["group"]
        if gid in by_id:
            raise OverlayError(
                "groups[%d]: '%s' already exists - use add_terms to extend it"
                % (i, gid))
        sev = g.get("severity", "high")
        if sev not in SEVERITIES:
            raise OverlayError("groups[%d] '%s': severity must be one of %s"
                               % (i, gid, ", ".join(sorted(SEVERITIES))))
        terms = _str_list(g.get("terms"), "groups[%d].terms" % i)
        grp = {"group": gid, "label": str(g.get("label", gid)),
               "severity": sev, "terms": terms}
        groups.append(grp)
        by_id[gid] = grp
        report["strengthened"].append(
            "added group '%s' (%d terms, %s)" % (gid, len(terms), sev))

    for gid, terms in _group_map(overlay.get("add_terms"), "add_terms").items():
        if gid not in by_id:
            raise OverlayError(
                "add_terms: no group '%s' - define it under groups first" % gid)
        have = {t.lower() for t in by_id[gid].setdefault("terms", [])}
        for t in terms:
            if t.lower() not in have:
                by_id[gid]["terms"].append(t)
                have.add(t.lower())
                report["strengthened"].append("added '%s' to %s" % (t, gid))

    for gid, terms in _group_map(overlay.get("remove_terms"),
                                 "remove_terms").items():
        if gid not in by_id:
            report["notes"].append("remove_terms: no group '%s'" % gid)
            continue
        current = by_id[gid].setdefault("terms", [])
        for t in terms:
            match = [x for x in current if x.lower() == t.lower()]
            if match:
                current.remove(match[0])
                report["weakened"].append("removed '%s' from %s" % (t, gid))
            else:
                report["notes"].append(
                    "remove_terms: '%s' is not in %s" % (t, gid))

    for p in _str_list(overlay.get("add_paths"), "add_paths"):
        if p not in pths:
            pths.append(p)
            report["strengthened"].append("added path '%s'" % p)
    for p in _str_list(overlay.get("remove_paths"), "remove_paths"):
        if p in pths:
            pths.remove(p)
            report["weakened"].append("removed path '%s'" % p)
        else:
            report["notes"].append("remove_paths: '%s' is not protected" % p)

    return merged, report


def load_keywords() -> Tuple[dict, dict]:
    """Shipped keywords with the user's overlay applied, plus a report."""
    shipped_path = paths.shipped(*SHIPPED_FILES["keywords.yaml"])
    shipped = _load(shipped_path)
    sources = [{"file": "keywords.yaml", "path": shipped_path,
                "source": "shipped", "sha256": sha256_short(shipped_path)}]
    user_path = paths.user_config("keywords.yaml")
    if os.path.isfile(user_path):
        try:
            overlay = _load(user_path)
            merged, report = merge_keywords(shipped, overlay)
        except (OverlayError, yaml.YAMLError) as exc:
            raise OverlayError("%s: %s" % (user_path, exc)) from exc
        sources.append({"file": "keywords.yaml", "path": user_path,
                        "source": "user overlay",
                        "sha256": sha256_short(user_path)})
    else:
        merged, report = merge_keywords(shipped, {})
    report["sources"] = sources
    return merged, report
