"""
Claude Code PreToolUse hook: security/policies/ and security/monitors/,
enforced on a coding agent's tool calls.

Claude Code runs this before every matching tool call, passing the call as
JSON on stdin. Exit 0 lets the call run. Exit 2 refuses it; the message on
stderr is shown to the agent. Install: hooks/README.md.

    ai-paladin-hook                    the hook itself (reads stdin)
    ai-paladin-hook --install [--user] add it to Claude Code's settings
    ai-paladin-hook --uninstall [--user]   remove it (do this before
                                       pip uninstall, or Claude Code refuses
                                       every tool call - see below)
    ai-paladin-hook --release SESSION  lift a fence-probing pause
    ai-paladin-hook --status           where it is installed; paused sessions

--install / --uninstall edit this project's .claude/settings.local.json
(personal, not committed), or with --user ~/.claude/settings.json (every
project). Only a person runs these: the hook refuses an agent that tries to
run them, or to edit those files.

What it enforces (each rule's `enforced:` line in the YAML says the same):

  commands.yaml   block patterns on Bash; write_scope on file-writing tools
  packages.yaml   pip / npm / cargo / poetry installs: allowlist, pinned
                  versions, nothing from URLs, paths or requirement files
  behavioral_rules.yaml
                  credential-path-access, out-of-scope-path, backup-tamper,
                  mass-file-touch, fence-probing

It FAILS CLOSED: if the hook itself errors, the tool call is refused. A gate
that opens when it breaks is not a gate.

LIMIT: this inspects tool calls, not what a shell command does once it runs.
It is a tripwire for careless or manipulated agents, not a sandbox.
"""

import fnmatch
import json
import os
import re
import shlex
import sys
import time
from datetime import datetime, timezone

WRITE_TOOLS = {"Write", "Edit", "MultiEdit", "NotebookEdit"}
READ_TOOLS = {"Read", "Grep", "Glob"}

# A Bash command naming a credential location.
_CRED_IN_SHELL = re.compile(
    r"""(^|[\s'"=:/~])\.(ssh|aws)(/|\s|$|['"])"""
    r"""|(^|[\s'"=/])\.env(\.[\w-]+)?(\s|$|['"])""")
_SEGMENT_SPLIT = re.compile(r"&&|\|\||[;|\n]")
# A Bash command that would switch the guard off or edit what it enforces.
_TAMPER_IN_SHELL = re.compile(
    r"ai-paladin-hook\s+--(release|uninstall|install)"
    r"|pre_tool_use\.py\s+--(release|uninstall|install)"
    r"|ai_paladin\.hook\s+--(release|uninstall|install)"
    r"|\.claude/settings(\.local)?\.json"
    r"|\.config/ai-paladin|hook-state"
    r"|pip3?\s+uninstall\s+(-y\s+)?ai[-_]paladin")


class Refused(Exception):
    def __init__(self, rule: str, reason: str):
        super().__init__(reason)
        self.rule, self.reason = rule, reason


# ---------------------------------------------------------------------------
# paths
# ---------------------------------------------------------------------------

def _real(path: str, cwd: str) -> str:
    p = os.path.expanduser(str(path))
    if not os.path.isabs(p):
        p = os.path.join(cwd, p)
    return os.path.realpath(p)       # a symlink cannot smuggle a write out


def _expand(entry: str, workspace: str, session: str) -> str:
    e = (str(entry).replace("${TASK_WORKSPACE}", workspace)
         .replace("${TASK_ID}", session))
    return os.path.expanduser(e)


def _under(path: str, root: str) -> bool:
    root = os.path.realpath(root)
    return path == root or path.startswith(root.rstrip("/") + "/")


def _matches(path: str, entry: str) -> bool:
    if any(c in entry for c in "*?["):
        return fnmatch.fnmatch(path, entry) or fnmatch.fnmatch("/" + path.lstrip("/"), entry)
    return _under(path, entry)


def check_write_path(path: str, cmds: dict, workspace: str, session: str):
    scope = cmds.get("write_scope") or {}
    for d in scope.get("deny") or []:
        if _matches(path, _expand(d, workspace, session)):
            rule = ("backup-tamper" if ("backup" in d or ".git/objects" in d)
                    else "out-of-scope-path")
            raise Refused(rule, "writing to %s is denied (write_scope.deny: %s)"
                          % (path, d))
    allow = [_expand(a, workspace, session) for a in scope.get("allow") or []]
    if allow and not any(_matches(path, a) for a in allow):
        raise Refused("out-of-scope-path",
                      "%s is outside the task workspace (write_scope.allow: %s)"
                      % (path, ", ".join(allow)))


def _protected(real: str) -> bool:
    """Files an agent must not edit: they decide what the guard enforces."""
    from ai_paladin import paths as ap
    if _under(real, ap.CONFIG_DIR) or _under(real, ap.LOG_DIR):
        return True
    parent, name = os.path.split(real)
    return (os.path.basename(parent) == ".claude"
            and name in ("settings.json", "settings.local.json"))


# ---------------------------------------------------------------------------
# package installs
# ---------------------------------------------------------------------------

def _tokens(segment: str) -> list:
    try:
        toks = shlex.split(segment)
    except ValueError:
        toks = segment.split()
    while toks and (re.match(r"^\w+=", toks[0]) or toks[0] in ("sudo", "env")):
        toks.pop(0)
    return toks


def _install_args(toks: list):
    """(ecosystem, args after the install verb) or None."""
    if not toks:
        return None
    t = [os.path.basename(toks[0])] + toks[1:]
    if re.match(r"^python[\d.]*$", t[0]) and t[1:3] == ["-m", "pip"]:
        t = ["pip"] + t[3:]
    if t[0] == "uv" and t[1:2] == ["pip"]:
        t = ["pip"] + t[2:]
    head = t[0]
    if head in ("pip", "pip3") and t[1:2] == ["install"]:
        return "pip", t[2:]
    if head == "npm" and t[1:2] and t[1] in ("install", "i", "add", "ci"):
        return "npm", t[2:]
    if head in ("pnpm", "yarn") and t[1:2] and t[1] in ("add", "install", "i"):
        return "npm", t[2:]
    if head == "cargo" and t[1:2] == ["add"]:
        return "cargo", t[2:]
    if head == "poetry" and t[1:2] == ["add"]:
        return "pip", t[2:]
    return None


def _spec(eco: str, spec: str):
    """(name, version or None) for a package argument."""
    if eco == "pip":
        m = re.match(r"^([A-Za-z0-9_.\-]+)(\[[^\]]*\])?(===?|@)?(.*)$", spec)
        if not m:
            return spec, None
        pinned = m.group(3) in ("==", "===", "@") and m.group(4)
        return m.group(1), (m.group(4) if pinned else None)
    at = spec.rfind("@")
    if at > 0:
        return spec[:at], spec[at + 1:] or None
    return spec, None


def _norm(eco: str, name: str) -> str:
    n = name.lower()
    return re.sub(r"[-_.]+", "-", n) if eco == "pip" else n


def check_install(eco: str, args: list, pkgs: dict):
    pol = pkgs.get("policy") or {}
    allow = (pkgs.get("allowlist") or {}).get(eco) or []
    default_block = pol.get("default", "block") == "block"
    specs, i = [], 0
    while i < len(args):
        a = args[i]
        if a in ("-r", "--requirement", "-e", "--editable", "-c",
                 "--constraint", "--index-url", "-i", "--extra-index-url",
                 "--find-links", "-f", "--registry", "--git", "--path"):
            if pol.get("block_install_from_url", True):
                raise Refused("packages.yaml", "`%s` installs from a file, "
                              "path or other source - not allowed" % a)
            i += 2
            continue
        if a.startswith("-"):
            i += 1
            continue
        specs.append(a)
        i += 1
    if not specs:
        if default_block:
            raise Refused("packages.yaml", "%s install without named packages "
                          "(from a manifest or lockfile) needs a person to "
                          "review it" % eco)
        return
    for s in specs:
        if pol.get("block_install_from_url", True) and (
                "://" in s or s.startswith(("git+", ".", "/", "~", "file:"))
                or s.endswith((".whl", ".tar.gz", ".zip", ".tgz"))):
            raise Refused("packages.yaml", "%r is a URL or path - packages "
                          "come from the allowlist only" % s)
        name, ver = _spec(eco, s)
        if pol.get("require_pinned_version", True) and not ver:
            raise Refused("packages.yaml", "%r has no pinned version (use %s)"
                          % (s, "name==x.y.z" if eco == "pip" else "name@x.y.z"))
        entry = next((e for e in allow
                      if _norm(eco, e.get("name", "")) == _norm(eco, name)), None)
        if entry is None:
            if default_block:
                raise Refused("packages.yaml", "%s package %r is not on the "
                              "allowlist - a person must add it to "
                              "packages.yaml" % (eco, name))
            continue
        want = str(entry.get("version", "*"))
        if ver and not fnmatch.fnmatch(ver, want):
            raise Refused("packages.yaml", "%s %s is not the allowlisted version "
                          "(%s)" % (name, ver, want))


# ---------------------------------------------------------------------------
# the decision
# ---------------------------------------------------------------------------

def evaluate(call: dict, cmds: dict, pkgs: dict, cred_globs: list):
    """Raise Refused if the call breaks a rule. Pure: no state, no I/O
    beyond resolving paths."""
    from ai_paladin.security.monitors import is_credential_path

    tool = call.get("tool_name", "")
    ti = call.get("tool_input") or {}
    cwd = call.get("cwd") or os.environ.get("CLAUDE_PROJECT_DIR") or os.getcwd()
    workspace = os.environ.get("CLAUDE_PROJECT_DIR") or cwd
    session = str(call.get("session_id") or "unknown")

    if tool == "Bash":
        command = str(ti.get("command", ""))
        for b in cmds.get("block") or []:
            if re.search(b["pattern"], command):
                raise Refused("commands.yaml", "command matches blocked "
                              "pattern %r" % b["pattern"])
        if _TAMPER_IN_SHELL.search(command):
            raise Refused("hook-tamper", "command would change or switch off "
                          "AI-Paladin's guard or its settings - only a person "
                          "may do that")
        if _CRED_IN_SHELL.search(command):
            raise Refused("credential-path-access", "command names a "
                          "credential location (.ssh, .aws or .env)")
        for seg in _SEGMENT_SPLIT.split(command):
            inst = _install_args(_tokens(seg))
            if inst:
                check_install(inst[0], inst[1], pkgs)
        return

    paths = [ti.get(k) for k in ("file_path", "notebook_path", "path")
             if ti.get(k)]
    for p in paths:
        real = _real(p, cwd)
        if is_credential_path(real, cred_globs) or is_credential_path(p, cred_globs):
            raise Refused("credential-path-access", "%s is a credential path" % p)
    if tool == "Glob" and _CRED_IN_SHELL.search(" " + str(ti.get("pattern", ""))):
        raise Refused("credential-path-access", "glob pattern targets a "
                      "credential location")
    if tool in WRITE_TOOLS:
        for p in paths:
            real = _real(p, cwd)
            if _protected(real):
                raise Refused("hook-tamper", "%s holds AI-Paladin's or Claude "
                              "Code's settings - only a person may edit it" % p)
            check_write_path(real, cmds, os.path.realpath(workspace), session)


# ---------------------------------------------------------------------------
# per-session state: fence-probing pause, mass-file-touch window
# ---------------------------------------------------------------------------

def _state_path(session: str) -> str:
    from ai_paladin import paths
    safe = re.sub(r"[^A-Za-z0-9_.-]", "_", session)[:120] or "unknown"
    return os.path.join(paths.LOG_DIR, "hook-state", safe + ".json")


def _load_state(session: str) -> dict:
    try:
        with open(_state_path(session), "r", encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return {"blocked": 0, "paused": False, "writes": []}


def _save_state(session: str, state: dict):
    p = _state_path(session)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    tmp = p + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(state, fh)
    os.replace(tmp, p)


def _log(record: dict):
    from ai_paladin import paths
    try:
        os.makedirs(paths.LOG_DIR, exist_ok=True)
        with open(os.path.join(paths.LOG_DIR, "hooks.jsonl"), "a",
                  encoding="utf-8") as fh:
            fh.write(json.dumps(record) + "\n")
    except OSError:
        pass


def decide(call: dict) -> tuple:
    """(allowed, message). Applies rules and session state, logs the result."""
    from ai_paladin import config_layers
    from ai_paladin.security import monitors

    cmds = config_layers.load_whole("commands.yaml")[0]
    pkgs = config_layers.load_whole("packages.yaml")[0]
    rules = monitors.load_rules()
    session = str(call.get("session_id") or "unknown")
    tool = call.get("tool_name", "")
    ti = call.get("tool_input") or {}
    detail = str(ti.get("command") or ti.get("file_path") or
                 ti.get("notebook_path") or ti.get("path") or
                 ti.get("pattern") or "")[:300]
    state = _load_state(session)
    rule, reason = None, None

    if state.get("paused"):
        rule, reason = "fence-probing", (
            "this session is paused after repeated refusals. A person must "
            "review it and run: ai-paladin-hook --release %s" % session)
    else:
        try:
            evaluate(call, cmds, pkgs, monitors.credential_globs(rules))
            if tool in WRITE_TOOLS:
                limit, window = monitors.write_limits(rules)
                now = time.time()
                writes = [t for t in state.get("writes", []) if now - t < window]
                if len(writes) >= limit:
                    raise Refused("mass-file-touch", "more than %d file writes "
                                  "in %ds" % (limit, window))
                writes.append(now)
                state["writes"] = writes
        except Refused as r:
            rule, reason = r.rule, r.reason

    if rule and not state.get("paused"):
        state["blocked"] = int(state.get("blocked", 0)) + 1
        if state["blocked"] > monitors.max_blocked(rules):
            state["paused"] = True
            reason += (" | Session PAUSED: %d refusals (fence-probing). A person "
                       "must run: ai-paladin-hook --release %s"
                       % (state["blocked"], session))
    _save_state(session, state)
    _log({"ts": datetime.now(timezone.utc).isoformat(), "kind": "hook",
          "session": session, "tool": tool,
          "decision": "blocked" if rule else "allowed",
          "rule": rule, "reason": reason, "detail": detail})
    if rule:
        return False, "AI-Paladin blocked this %s call [%s]: %s" % (
            tool, rule, reason)
    return True, ""


# ---------------------------------------------------------------------------
# turning it on and off: Claude Code's settings
# ---------------------------------------------------------------------------

MATCHER = "Bash|Write|Edit|MultiEdit|NotebookEdit|Read|Grep|Glob"


def settings_file(user: bool) -> str:
    if user:
        return os.path.join(os.path.expanduser("~"), ".claude", "settings.json")
    root = os.environ.get("CLAUDE_PROJECT_DIR") or os.getcwd()
    return os.path.join(root, ".claude", "settings.local.json")


def hook_command() -> str:
    """The command Claude Code runs. `|| exit 2` makes any failure to start
    - python3 missing, folder moved - a refusal, not a pass."""
    from ai_paladin import paths as ap
    wrapper = os.path.join(ap.BASE, "hooks", "pre_tool_use.py")
    return "%s %s || exit 2" % (shlex.quote(sys.executable),
                                shlex.quote(wrapper))


def _is_ours(entry: dict) -> bool:
    return any("pre_tool_use.py" in str(h.get("command", ""))
               or "ai-paladin-hook" in str(h.get("command", ""))
               for h in entry.get("hooks", []) if isinstance(h, dict))


def _read_settings(path: str) -> dict:
    if not os.path.exists(path):
        return {}
    with open(path, "r", encoding="utf-8") as fh:
        text = fh.read()
    data = json.loads(text) if text.strip() else {}
    if not isinstance(data, dict):
        raise ValueError("%s: top level is not a JSON object" % path)
    return data


def _write_settings(path: str, data: dict):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    if os.path.exists(path):
        with open(path, "rb") as src, open(path + ".bak", "wb") as dst:
            dst.write(src.read())
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=2)
        fh.write("\n")
    os.replace(tmp, path)


def install(user: bool) -> int:
    path = settings_file(user)
    try:
        data = _read_settings(path)
    except (OSError, ValueError) as exc:
        print("not changed - cannot read %s: %s" % (path, exc), file=sys.stderr)
        return 1
    pre = data.setdefault("hooks", {}).setdefault("PreToolUse", [])
    pre[:] = [e for e in pre if not (isinstance(e, dict) and _is_ours(e))]
    pre.append({"matcher": MATCHER,
                "hooks": [{"type": "command", "command": hook_command()}]})
    _write_settings(path, data)
    _log({"ts": datetime.now(timezone.utc).isoformat(), "kind": "hook",
          "decision": "installed", "detail": path})
    print("installed in %s\n  %s\nClaude Code picks it up in new sessions. "
          "Remove it with: ai-paladin-hook --uninstall%s"
          % (path, hook_command(), " --user" if user else ""))
    return 0


def uninstall(user: bool) -> int:
    path = settings_file(user)
    try:
        data = _read_settings(path)
    except (OSError, ValueError) as exc:
        print("not changed - cannot read %s: %s" % (path, exc), file=sys.stderr)
        return 1
    pre = (data.get("hooks") or {}).get("PreToolUse") or []
    kept = [e for e in pre if not (isinstance(e, dict) and _is_ours(e))]
    if len(kept) == len(pre):
        print("not installed in %s" % path)
        return 0
    if kept:
        data["hooks"]["PreToolUse"] = kept
    else:
        del data["hooks"]["PreToolUse"]
        if not data["hooks"]:
            del data["hooks"]
    _write_settings(path, data)
    _log({"ts": datetime.now(timezone.utc).isoformat(), "kind": "hook",
          "decision": "uninstalled", "detail": path})
    print("removed from %s" % path)
    return 0


def where_installed() -> list:
    out = []
    for user in (False, True):
        p = settings_file(user)
        try:
            pre = ((_read_settings(p).get("hooks") or {})
                   .get("PreToolUse") or [])
        except (OSError, ValueError):
            continue
        if any(isinstance(e, dict) and _is_ours(e) for e in pre):
            out.append(p)
    return out


def main(argv=None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if argv and argv[0] in ("--install", "--uninstall") and \
            set(argv[1:]) <= {"--user"}:
        user = "--user" in argv[1:]
        return install(user) if argv[0] == "--install" else uninstall(user)
    if argv[:1] == ["--release"] and len(argv) == 2:
        p = _state_path(argv[1])
        if os.path.exists(p):
            os.remove(p)
            _log({"ts": datetime.now(timezone.utc).isoformat(), "kind": "hook",
                  "session": argv[1], "decision": "released",
                  "rule": "fence-probing", "reason": "released by a person"})
            print("released %s" % argv[1])
            return 0
        print("no state for %s" % argv[1], file=sys.stderr)
        return 1
    if argv[:1] == ["--status"]:
        from ai_paladin import paths
        places = where_installed()
        print("installed in   %s" % ("\n               ".join(places)
                                     if places else "nowhere (this project "
                                     "or ~/.claude) - run --install"))
        d = os.path.join(paths.LOG_DIR, "hook-state")
        for f in sorted(os.listdir(d)) if os.path.isdir(d) else []:
            try:
                st = json.load(open(os.path.join(d, f), encoding="utf-8"))
            except (OSError, ValueError):
                continue
            print("%-40s blocked=%d %s" % (f[:-5], st.get("blocked", 0),
                                          "PAUSED" if st.get("paused") else ""))
        return 0
    if argv:
        print("usage: ai-paladin-hook [--install [--user] | --uninstall "
              "[--user] | --release SESSION | --status]", file=sys.stderr)
        return 1

    try:
        call = json.load(sys.stdin)
        if call.get("hook_event_name", "PreToolUse") != "PreToolUse":
            return 0
        allowed, message = decide(call)
    except Exception as exc:                    # fail closed
        print("AI-Paladin hook error - refusing the call rather than letting "
              "it through unchecked: %s: %s" % (type(exc).__name__, exc),
              file=sys.stderr)
        return 2
    if allowed:
        return 0
    print(message, file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main())
