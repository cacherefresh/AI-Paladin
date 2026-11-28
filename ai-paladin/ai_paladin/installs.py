"""
What AI-Paladin put OUTSIDE Python, and how to take back exactly that.

pip cannot run code when it uninstalls a package, so the Claude Code hook
entries that `ai-paladin-hook --install` writes into settings files would be
left behind. `ai-paladin uninstall` (run BEFORE `pip uninstall ai-paladin`)
removes them. To do that without guessing, every install writes an install
manifest, install_manifest.json in the config folder (~/.config/ai-paladin,
or $AI_PALADIN_CONFIG_DIR), recording per settings file:

  added            each hook entry WE wrote: the event, the matcher, what it
                   runs, and a SHA-256 fingerprint of the entry as written
  already_present  equivalent AI-Paladin entries that were in the file before
                   we installed. We did not write them, so we never remove them

Uninstalling removes only entries whose fingerprint matches an `added`
record. It is NOT a snapshot revert: hooks that existed before install, and
hooks other tools add afterwards, are never touched. An entry of ours whose
fingerprint no longer matches was edited after install; it is flagged, and
kept unless the person says to remove it.

The manifest lives in the config folder, which the hook-tamper rule keeps
agents out of. `ai-paladin uninstall` is a command a person runs; the hook
refuses an agent that tries to run it.
"""

import hashlib
import json
import os
import re
from datetime import datetime, timezone

MANIFEST = "install_manifest.json"
LEGACY_REGISTRY = "hook_installs.json"     # written by earlier versions
EVENT = "PreToolUse"
VERSION = 1


class ManifestError(Exception):
    """The manifest exists but cannot be read. Nothing is removed on a guess."""


def _hook():
    from ai_paladin import hook         # late: hook.py imports this module late too
    return hook


def fingerprint(entry: dict) -> str:
    """SHA-256 of an entry in a canonical form (key order does not matter)."""
    blob = json.dumps(entry, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def short(fp: str) -> str:
    return fp[:12]


def summarize(entry: dict) -> str:
    """One line saying what a hook entry runs, for the prompt and the manifest."""
    cmds = [str(h.get("command", "")) for h in entry.get("hooks", [])
            if isinstance(h, dict)]
    text = " ; ".join(cmds)
    m = re.search(r"(\S*pre_tool_use\.py)", text) or re.search(r"(\S*ai-paladin-hook)", text)
    what = ("runs " + m.group(1).strip("'\"")) if m else text[:70]
    return '%s matcher "%s" %s' % (EVENT, entry.get("matcher", ""), what)


def manifest_path() -> str:
    from ai_paladin import paths
    return os.path.join(paths.CONFIG_DIR, MANIFEST)


def _legacy_path() -> str:
    from ai_paladin import paths
    return os.path.join(paths.CONFIG_DIR, LEGACY_REGISTRY)


def legacy_files() -> list:
    """Settings files an earlier version recorded, without fingerprints."""
    try:
        with open(_legacy_path(), "r", encoding="utf-8") as fh:
            return [str(p) for p in json.load(fh).get("settings_files", [])]
    except (OSError, ValueError, AttributeError):
        return []


def _set_legacy(files: list):
    p = _legacy_path()
    if not files:
        if os.path.exists(p):
            os.remove(p)
        return
    with open(p, "w", encoding="utf-8") as fh:
        json.dump({"settings_files": sorted(set(files))}, fh, indent=2)
        fh.write("\n")


def load() -> dict:
    """{file: record}. Empty if no manifest. ManifestError if unreadable."""
    p = manifest_path()
    if not os.path.exists(p):
        return {}
    try:
        with open(p, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        recs = data["installs"]
        out = {}
        for r in recs:
            out[str(r["file"])] = {
                "file": str(r["file"]),
                "added": [dict(a) for a in r.get("added", [])],
                "already_present": [dict(a) for a in r.get("already_present", [])],
            }
            for a in out[str(r["file"])]["added"] + out[str(r["file"])]["already_present"]:
                a["fingerprint"]            # KeyError if malformed
        return out
    except (OSError, ValueError, KeyError, TypeError, AttributeError) as exc:
        raise ManifestError("%s cannot be read (%s: %s)"
                            % (p, type(exc).__name__, exc))


def save(records: dict):
    """Write the manifest; delete it when nothing is recorded any more."""
    p = manifest_path()
    live = [r for _, r in sorted(records.items())
            if r["added"] or r["already_present"]]
    if not live:
        if os.path.exists(p):
            os.remove(p)
        return
    os.makedirs(os.path.dirname(p), exist_ok=True)
    tmp = p + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump({"version": VERSION, "event": EVENT, "installs": live},
                  fh, indent=2)
        fh.write("\n")
    os.replace(tmp, p)


def _pre(data: dict) -> list:
    pre = (data.get("hooks") or {}).get(EVENT) or []
    return pre if isinstance(pre, list) else []


def _ours_idx(pre: list) -> list:
    hook = _hook()
    return [i for i, e in enumerate(pre) if isinstance(e, dict) and hook._is_ours(e)]


def _stamp(entry: dict, **extra) -> dict:
    d = {"fingerprint": fingerprint(entry), "matcher": entry.get("matcher", ""),
         "summary": summarize(entry)}
    d.update(extra)
    return d


# ---------------------------------------------------------------------------
# install
# ---------------------------------------------------------------------------

def apply_install(path: str, data: dict, entry: dict) -> dict:
    """Put `entry` into settings `data` (in place) and update the manifest.
    The manifest is written first: if that fails nothing has changed, and a
    manifest that is ahead of the settings file only ever over-reports.
    Returns {"replaced": n, "kept": [summaries], "added": bool}."""
    records = load()
    rec = records.get(path)
    legacy = path in legacy_files()
    pre = data.setdefault("hooks", {}).setdefault(EVENT, [])
    fe = fingerprint(entry)

    recorded = {a["fingerprint"] for a in (rec or {}).get("added", [])}
    matched, unmatched = [], []
    for i in _ours_idx(pre):
        (matched if fingerprint(pre[i]) in recorded else unmatched).append(i)
    found = {fingerprint(pre[i]) for i in matched}
    missing = len(recorded - found)         # recorded entries since edited
    if rec is None and legacy:
        adopt = list(unmatched)             # an earlier version wrote these
    else:
        adopt = unmatched[:missing]         # ours, edited: replace on reinstall
    replace = set(matched) | set(adopt)
    kept = [i for i in unmatched if i not in adopt]

    pre_same = [i for i in kept if fingerprint(pre[i]) == fe]
    already = {a["fingerprint"]: a for a in (rec or {}).get("already_present", [])
               if any(fingerprint(pre[i]) == a["fingerprint"] for i in kept)}
    for i in kept:
        already[fingerprint(pre[i])] = _stamp(pre[i])

    add_it = not pre_same
    new_rec = {"file": path, "already_present": list(already.values()),
               "added": ([_stamp(entry, added_at=datetime.now(timezone.utc)
                                 .isoformat(timespec="seconds"))]
                         if add_it else [])}
    records[path] = new_rec
    save(records)
    if legacy:
        _set_legacy([p for p in legacy_files() if p != path])

    pre[:] = [e for i, e in enumerate(pre) if i not in replace]
    if add_it:
        pre.append(entry)
    return {"replaced": len(replace), "added": add_it,
            "kept": [a["summary"] for a in already.values()]}


# ---------------------------------------------------------------------------
# uninstall
# ---------------------------------------------------------------------------

def inspect(path: str, rec: dict | None) -> dict:
    """What removing our additions from one settings file would do.

      remove    [(fingerprint, summary)]  entries we added, unchanged
      modified  [(recorded_fp, now_fp, summary)]  ours, edited since install
      gone      [fingerprint]  we added it, it is no longer there
      kept      [summary]  was already present before install
      legacy    True when an earlier version recorded this file (no
                fingerprints): every AI-Paladin entry in it is ours
      error     text if the file exists but cannot be read
    """
    hook = _hook()
    out = {"file": path, "remove": [], "modified": [], "gone": [], "kept": [],
           "legacy": rec is None, "error": None, "exists": os.path.exists(path)}
    if not out["exists"]:
        return out
    try:
        pre = _pre(hook._read_settings(path))
    except (OSError, ValueError) as exc:
        out["error"] = str(exc)
        return out
    ours = _ours_idx(pre)
    if rec is None:                                    # legacy record
        out["remove"] = [(fingerprint(pre[i]), summarize(pre[i])) for i in ours]
        return out
    used = set()
    missing = []
    for a in rec["added"]:
        hit = next((i for i in ours if i not in used
                    and fingerprint(pre[i]) == a["fingerprint"]), None)
        if hit is None:
            missing.append(a)
        else:
            used.add(hit)
            out["remove"].append((a["fingerprint"], summarize(pre[hit])))
    pre_fps = {a["fingerprint"] for a in rec["already_present"]}
    for i in ours:
        if i not in used and fingerprint(pre[i]) in pre_fps:
            out["kept"].append(summarize(pre[i]))
            used.add(i)
    rest = [i for i in ours if i not in used]
    for a, i in zip(missing, rest):
        out["modified"].append((a["fingerprint"], fingerprint(pre[i]),
                                summarize(pre[i])))
    out["gone"] = [a["fingerprint"] for a in missing[len(rest):]]
    return out


def plan() -> list:
    """One inspect() result per settings file we recorded (manifest first,
    then files only an earlier version recorded)."""
    records = load()
    items = [inspect(p, r) for p, r in sorted(records.items())]
    items += [inspect(p, None) for p in legacy_files() if p not in records]
    return items


def has_work(item: dict) -> bool:
    return bool(item["remove"] or item["modified"])


def _drop(path: str, fps: list, modified_now: list):
    """Remove from `path` one entry per fingerprint in `fps` (+ the modified
    entries whose current fingerprint is in `modified_now`). Nothing else."""
    hook = _hook()
    data = hook._read_settings(path)
    pre = _pre(data)
    want = list(fps) + list(modified_now)
    keep = []
    for e in pre:
        fp = fingerprint(e) if isinstance(e, dict) else None
        if fp in want and hook._is_ours(e):
            want.remove(fp)
            continue
        keep.append(e)
    if len(keep) == len(pre):
        return
    if keep:
        data["hooks"][EVENT] = keep
    else:
        del data["hooks"][EVENT]
        if not data["hooks"]:
            del data["hooks"]
    hook._write_settings(path, data)
    hook._log({"ts": datetime.now(timezone.utc).isoformat(), "kind": "hook",
               "decision": "uninstalled", "detail": path})


def remove(item: dict, include_modified: bool = False):
    """Remove what inspect() found for one file, then update the manifest.
    Entries flagged as modified are removed only with include_modified.
    Raises OSError/ValueError if the file cannot be written."""
    path = item["file"]
    fps = [fp for fp, _ in item["remove"]]
    mods = [now for _, now, _ in item["modified"]] if include_modified else []
    if item["exists"]:
        _drop(path, fps, mods)
    if item["legacy"]:
        _set_legacy([p for p in legacy_files() if p != path])
        return
    records = load()
    rec = records.get(path)
    if rec is None:
        return
    done = set(fps) | set(item["gone"])
    if include_modified:
        done |= {recorded for recorded, _, _ in item["modified"]}
    if not item["exists"]:
        done |= {a["fingerprint"] for a in rec["added"]}
    rec["added"] = [a for a in rec["added"] if a["fingerprint"] not in done]
    if not rec["added"]:
        rec["already_present"] = []          # nothing of ours left to track
    save(records)


def files_with_work() -> list:
    out = []
    try:
        for it in plan():
            if has_work(it):
                out.append(it["file"])
    except ManifestError:
        pass
    return out
