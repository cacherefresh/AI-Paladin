"""
Claude Code PreToolUse hook: security/policies/ and security/monitors/,
enforced on a coding agent's tool calls.

Claude Code runs this before every matching tool call, passing the call as
JSON on stdin. Exit 0 lets the call run. Exit 2 refuses it; the message on
stderr is shown to the agent. Install: hooks/README.md.

    ai-paladin-hook                    the hook itself (reads stdin)
    ai-paladin-hook --install [--user] add it to Claude Code's settings
    ai-paladin-hook --uninstall --all  remove it from every recorded place
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
                  mass-file-touch, fence-probing, hook-tamper (including
                  AI-Paladin's own policy files)

Bash commands are parsed (ai_paladin/shell_scan.py) and code handed to an
interpreter is read (ai_paladin/code_scan.py), so the rules apply to
commands nested in sh -c / eval / $(...), to paths however they are spelled,
and to the files a command or an agent-written script writes.

It FAILS CLOSED: if the hook itself errors, the tool call is refused. A gate
that opens when it breaks is not a gate.

LIMIT: this reads tool calls and the code they would run; it does not run
them. Anything decided at run time (a computed path, a decoded string, an
imported module) is not seen. It is a hardened guardrail, not a sandbox or
a security boundary (docs/ROADMAP.md, section 9).
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
# The two halves of _CRED_IN_SHELL: key folders, and .env files (which the
# opt-in hook.yaml setting scripts_may_read_env_files lets script files name).
_CRED_KEYS_IN_SHELL = re.compile(r"""(^|[\s'"=:/~])\.(ssh|aws)(/|\s|$|['"])""")
_CRED_ENV_IN_SHELL = re.compile(r"""(^|[\s'"=/])\.env(\.[\w-]+)?(\s|$|['"])""")
_ENV_FILE = re.compile(r"(^|/)\.env(\.[^/]+)?/?$")


def _names_credential(text: str, env_ok: bool = False) -> bool:
    return bool(_CRED_KEYS_IN_SHELL.search(text) or
                (not env_ok and _CRED_ENV_IN_SHELL.search(text)))


def _credential(path: str, cwd: str, globs: list, env_ok: bool = False) -> bool:
    """Is `path` (as written, or resolved) a credential path? With env_ok, a
    .env / .env.* file outside .ssh and .aws is not."""
    from ai_paladin.security.monitors import is_credential_path
    real = _real(path, cwd)
    if not (is_credential_path(path, globs) or is_credential_path(real, globs)):
        return False
    if env_ok and all(_ENV_FILE.search(p) and not _CRED_KEYS_IN_SHELL.search(p)
                      for p in (path, real)):
        return False
    return True


_CRED_IN_SHELL = re.compile(
    r"""(^|[\s'"=:/~])\.(ssh|aws)(/|\s|$|['"])"""
    r"""|(^|[\s'"=/])\.env(\.[\w-]+)?(\s|$|['"])""")
# A Bash command that would switch the guard off or edit what it enforces.
_TAMPER_IN_SHELL = re.compile(
    r"ai-paladin-hook\s+--(release|uninstall|install)"
    r"|pre_tool_use\.py\s+--(release|uninstall|install)"
    r"|ai_paladin\.hook\s+--(release|uninstall|install)"
    r"|\.claude/settings(\.local)?\.json"
    r"|\.config/ai-paladin|hook-state"
    r"|pip3?\s+uninstall\s+(-y\s+)?ai[-_]paladin"
    r"|ai-paladin\s+uninstall|ai_paladin\s+uninstall"
    r"|hook_installs\.json")


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


def check_write_path(path: str, cmds: dict, workspace: str, session: str,
                     use_allow: bool = True):
    """Refuse a write to `path` outside commands.yaml write_scope. With
    use_allow=False only `deny` applies (used for Bash commands)."""
    scope = cmds.get("write_scope") or {}
    for d in scope.get("deny") or []:
        if _matches(path, _expand(d, workspace, session)):
            rule = ("backup-tamper" if ("backup" in d or ".git/objects" in d)
                    else "out-of-scope-path")
            raise Refused(rule, "writing to %s is denied (write_scope.deny: %s)"
                          % (path, d))
    if not use_allow:
        return
    allow = [_expand(a, workspace, session) for a in scope.get("allow") or []]
    if allow and not any(_matches(path, a) for a in allow):
        raise Refused("out-of-scope-path",
                      "%s is outside the task workspace (write_scope.allow: %s)"
                      % (path, ", ".join(allow)))


def _guard_dirs() -> list:
    """AI-Paladin's config and log folders: the ones in use, and the default
    XDG locations too, so pointing AI_PALADIN_*_DIR elsewhere does not leave
    the usual copies open to an agent."""
    from ai_paladin import paths as ap
    home = os.path.expanduser("~")
    xdg_config = os.environ.get("XDG_CONFIG_HOME") or os.path.join(home, ".config")
    xdg_state = (os.environ.get("XDG_STATE_HOME")
                 or os.path.join(home, ".local", "state"))
    dirs = [ap.CONFIG_DIR, ap.LOG_DIR,
            os.path.join(xdg_config, "ai-paladin"),
            os.path.join(xdg_state, "ai-paladin"),
            os.path.join(home, ".config", "ai-paladin"),
            os.path.join(home, ".local", "state", "ai-paladin")]
    return sorted({os.path.realpath(d) for d in dirs})


# The enforcement files of an AI-Paladin tree (AGENTS.md: "the gates are
# data, not prose"). Relative to the tree's root - ai-paladin/ in the
# repository, ai_paladin/_shipped/ in a wheel.
POLICY_FILES = ("router/keywords.yaml", "router/policy.yaml",
                "config/keywords.yaml")
POLICY_DIRS = ("security/policies", "security/monitors")


def _paladin_root(root: str) -> bool:
    """Is `root` an AI-Paladin tree: the one this hook runs from, or a
    checkout of it (the ai_paladin package or hooks/ wrapper beside it)?"""
    from ai_paladin import paths as ap
    r = os.path.realpath(root or "/")
    return (r == os.path.realpath(ap.BASE)
            or os.path.isfile(os.path.join(r, "ai_paladin", "hook.py"))
            or os.path.isfile(os.path.join(r, "hooks", "pre_tool_use.py")))


def _policy_file(real: str) -> bool:
    for rel in POLICY_FILES:
        if real.endswith("/" + rel) and _paladin_root(real[:-len(rel) - 1]):
            return True
    for d in POLICY_DIRS:
        i = real.find("/" + d)
        while i >= 0:
            end = i + 1 + len(d)
            if (end == len(real) or real[end] == "/") and _paladin_root(real[:i]):
                return True
            i = real.find("/" + d, i + 1)
    return False


def _policy_locations(workspace: str) -> list:
    """The enforcement files of every AI-Paladin tree the hook knows of: its
    own, and the project's if the project is (or contains) a checkout."""
    from ai_paladin import paths as ap
    roots = {os.path.realpath(r) for r in
             (ap.BASE, workspace, os.path.join(workspace, "ai-paladin"))
             if _paladin_root(r)}
    return [os.path.join(r, rel) for r in sorted(roots)
            for rel in POLICY_FILES + POLICY_DIRS]


def _protected(real: str) -> bool:
    """Files an agent must not edit: they decide what the guard enforces -
    AI-Paladin's config and log folders, Claude Code's settings, and the
    policy files of an AI-Paladin tree."""
    if any(_under(real, d) for d in _guard_dirs()):
        return True
    if _policy_file(real):
        return True
    parent, name = os.path.split(real)
    return (os.path.basename(parent) == ".claude"
            and name in ("settings.json", "settings.local.json"))


def _holds_protected(real: str, workspace: str) -> bool:
    """True if deleting or moving `real` would take protected files with it
    (`rm -rf ~/.config`, `mv .claude elsewhere`)."""
    held = (_guard_dirs() + _policy_locations(workspace)
            + [os.path.join(workspace, ".claude"),
               os.path.join(os.path.expanduser("~"), ".claude")])
    return any(_under(os.path.realpath(h), real) for h in held)


# ---------------------------------------------------------------------------
# package installs
# ---------------------------------------------------------------------------

def _install_args(toks: list):
    """(ecosystem, args after the install verb) or None. `toks` are a
    command's words with wrappers (sudo, env, VAR=...) already removed."""
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

# How deep sh -c 'bash -c "eval ..."' may nest before the hook stops reading
# and refuses: a real command rarely nests more than twice.
MAX_SHELL_DEPTH = 6


def _check_bash(command: str, cmds: dict, pkgs: dict, cred_globs: list,
                cwd: str, workspace: str, session: str, depth: int = 0,
                strict: bool = False, env_ok: bool = False,
                scripts_env: bool = False):
    """
    Apply the Bash rules to a command and to every command nested in it.
    `sh -c '...'`, `bash -c "..."`, eval, $(...), backticks and a here-doc
    fed to a shell are unwrapped (ai_paladin/shell_scan.py) and checked as
    if the agent had typed them directly.
    """
    from ai_paladin import shell_scan

    if depth > MAX_SHELL_DEPTH:
        raise Refused("commands.yaml", "command nests shells more than %d "
                      "deep - too deep to inspect" % MAX_SHELL_DEPTH)
    for b in cmds.get("block") or []:
        if re.search(b["pattern"], command):
            raise Refused("commands.yaml", "command matches blocked "
                          "pattern %r" % b["pattern"])
    if _TAMPER_IN_SHELL.search(command):
        raise Refused("hook-tamper", "command would change or switch off "
                      "AI-Paladin's guard or its settings - only a person "
                      "may do that")
    if _names_credential(command, env_ok):
        raise Refused("credential-path-access", "command names a "
                      "credential location (.ssh, .aws or .env)")

    sc = shell_scan.scan(command)
    # The same text with the shell's quoting removed: `~/.ss''h` and
    # `--rel""ease` read as what bash will actually run.
    flat = " ".join(sc.words + [t for s in sc.segments
                                for _, t in s.redirects])
    if _TAMPER_IN_SHELL.search(flat):
        raise Refused("hook-tamper", "command would change or switch off "
                      "AI-Paladin's guard or its settings - only a person "
                      "may do that")
    if _names_credential(flat, env_ok):
        raise Refused("credential-path-access", "command names a "
                      "credential location (.ssh, .aws or .env)")
    env = dict(os.environ)
    here = cwd
    for seg in sc.segments:
        env.update(seg.assigns)
        for word in seg.words + [t for _, t in seg.redirects]:
            for p in shell_scan.word_paths(word, env, here):
                if _credential(p, here, cred_globs, env_ok):
                    raise Refused("credential-path-access", "%r resolves to "
                                  "a credential path (%s)" % (word, p))
        inst = _install_args(seg.words)
        if inst:
            check_install(inst[0], inst[1], pkgs)
        for word, kind in shell_scan.write_targets(seg):
            for p in shell_scan.expand_word(word, env, here):
                _check_shell_write(p, kind, here, cmds, workspace, session,
                                   strict)
        for inner in seg.inner:
            _check_bash(inner, cmds, pkgs, cred_globs, here, workspace,
                        session, depth + 1, strict, env_ok)
        for lang, source, from_file in shell_scan.programs(seg, env, here):
            # a script file may name .env files only if hook.yaml says so;
            # inline code (-c, -e, here-docs) is the same as typing it
            ok = env_ok or (from_file and scripts_env)
            if lang == "shell":
                _check_bash(source, cmds, pkgs, cred_globs, here, workspace,
                            session, depth + 1, strict, ok,
                            scripts_env=scripts_env)
            else:
                _check_code(source, lang, cmds, pkgs, cred_globs, here,
                            workspace, session, depth + 1, strict, ok,
                            scripts_env=scripts_env)
        if seg.name in ("cd", "pushd"):          # later segments run there
            dest = seg.words[1] if len(seg.words) > 1 else "~"
            if dest != "-":
                here = _real(shell_scan.expand_word(dest, env, here)[0], here)
    for inner in sc.substitutions:
        _check_bash(inner, cmds, pkgs, cred_globs, cwd, workspace, session,
                    depth + 1, strict, env_ok, scripts_env=scripts_env)


def _check_code(source: str, lang: str, cmds: dict, pkgs: dict,
                cred_globs: list, cwd: str, workspace: str, session: str,
                depth: int, strict: bool = False, env_ok: bool = False,
                scripts_env: bool = False):
    """
    Code handed to an interpreter (python3 -c, a script the agent wrote,
    perl -e, ...): the files it writes get the same checks as a Bash write,
    the paths it names the credential check, and the shell commands it runs
    (os.system, subprocess) every Bash rule (ai_paladin/code_scan.py).
    """
    from ai_paladin import code_scan, shell_scan

    if depth > MAX_SHELL_DEPTH:
        raise Refused("commands.yaml", "code nests more than %d levels deep "
                      "- too deep to inspect" % MAX_SHELL_DEPTH)
    writes, shells, strings = code_scan.effects(source, lang)
    env = dict(os.environ)
    for s in strings:
        s = code_scan.strip_mode(s)
        if not s or len(s) > 4096 or any(ch.isspace() for ch in s):
            continue                     # prose, not a path
        if _names_credential(" " + s + " ", env_ok) or any(
                _credential(p, cwd, cred_globs, env_ok)
                for p in shell_scan.expand_word(s, env, cwd)):
            raise Refused("credential-path-access", "%s code names a "
                          "credential path (%s)" % (lang, s))
    for target, kind in writes:
        for p in shell_scan.expand_word(code_scan.strip_mode(target), env, cwd):
            if _credential(p, cwd, cred_globs):     # writing one: never
                raise Refused("credential-path-access", "%s code writes a "
                              "credential path (%s)" % (lang, p))
            _check_shell_write(p, kind, cwd, cmds, workspace, session,
                               strict)
    for command in shells:
        _check_bash(command, cmds, pkgs, cred_globs, cwd, workspace, session,
                    depth + 1, strict, env_ok, scripts_env=scripts_env)


# Not files: writing here goes to a terminal or nowhere.
_NOT_FILES = re.compile(r"^/dev/(null|zero|stdout|stderr|stdin|tty|fd/\d+)$"
                        r"|^/proc/self/fd/\d+$")


def _check_shell_write(path: str, kind: str, cwd: str, cmds: dict,
                       workspace: str, session: str, strict: bool = False):
    """A file a Bash command or interpreter code writes (>, tee, cp, mv, rm,
    sed -i, dd of=, open(..., 'w'), ...). Protected files and
    write_scope.deny always apply, as for the Write tool.

    write_scope.allow applies only when `strict` - the opt-in
    shell_writes_enforce_allow setting in hook.yaml (load_hook_settings).
    By default it does not: ordinary shell work (rm -rf /tmp/build, a cache
    in ~) writes outside the project."""
    if _NOT_FILES.match(path):
        return
    real = _real(path, cwd)
    if _protected(real) or (kind == "destroy"
                            and _holds_protected(real, workspace)):
        raise Refused("hook-tamper", "command would write, move or delete %s, "
                      "which holds AI-Paladin's policy, settings or audit log "
                      "or Claude Code's settings - only a person may do that"
                      % path)
    check_write_path(real, cmds, workspace, session, use_allow=strict)
    if kind == "destroy":
        # deleting a folder deletes what is in it: `rm -rf backup` is a
        # write to backup/** as much as `rm backup/db` is
        check_write_path(os.path.join(real, "_"), cmds, workspace, session,
                         use_allow=strict)


# ---------------------------------------------------------------------------
# the hook's own settings: hook.yaml in the user's settings folder
# ---------------------------------------------------------------------------

HOOK_SETTINGS = "hook.yaml"
HOOK_SETTING_DEFAULTS = {
    # Also hold files written by Bash commands and interpreter code to
    # commands.yaml write_scope.allow (default-deny outside the allowed
    # folders), not only to write_scope.deny. Off by default.
    "shell_writes_enforce_allow": False,
    # Let a script FILE the agent runs (python3 app.py, ./run.sh, source x)
    # name .env / .env.* files - e.g. load_dotenv(".env") - instead of the
    # whole call being refused. Never .ssh or .aws, never writing a .env,
    # never inline code or a typed command (cat .env). Off by default.
    "scripts_may_read_env_files": False,
}


def load_hook_settings() -> dict:
    """
    ~/.config/ai-paladin/hook.yaml (AI_PALADIN_CONFIG_DIR/hook.yaml), over
    HOOK_SETTING_DEFAULTS. No file means the defaults. The file lives in the
    config folder the hook-tamper rule keeps agents out of, so only a person
    can change it. An unknown key or a non-boolean value raises ValueError:
    the hook then refuses every call (fail closed) rather than silently run
    without a setting the user meant to turn on.
    """
    import yaml
    from ai_paladin import paths
    out = dict(HOOK_SETTING_DEFAULTS)
    p = paths.user_config(HOOK_SETTINGS)
    if not os.path.exists(p):
        return out
    with open(p, "r", encoding="utf-8") as fh:
        data = yaml.safe_load(fh)
    if data is None:
        return out
    if not isinstance(data, dict):
        raise ValueError("%s: top level must be a mapping" % p)
    unknown = sorted(set(data) - set(HOOK_SETTING_DEFAULTS))
    if unknown:
        raise ValueError("%s: unknown setting(s) %s - known: %s" % (
            p, ", ".join(map(str, unknown)),
            ", ".join(sorted(HOOK_SETTING_DEFAULTS))))
    for k, v in data.items():
        if not isinstance(v, bool):
            raise ValueError("%s: %s must be true or false, not %r" % (p, k, v))
        out[k] = v
    return out


_MCP_PATH_KEY = re.compile(r"(path|file|filename|dir|directory|dest|"
                           r"destination|source|target)s?$", re.I)
_MCP_WRITE_TOOL = re.compile(r"write|edit|create|delete|remove|move|rename|"
                             r"mkdir|upload|save|append|patch|put|copy", re.I)


def _mcp_paths(ti: dict) -> list:
    out = []
    for k, v in ti.items():
        if not _MCP_PATH_KEY.search(str(k)):
            continue
        for item in (v if isinstance(v, list) else [v]):
            if isinstance(item, str) and item and "://" not in item:
                out.append(item)
    return out


def evaluate(call: dict, cmds: dict, pkgs: dict, cred_globs: list,
             settings: dict = None):
    """Raise Refused if the call breaks a rule. No state; the only I/O is
    resolving paths, reading a script a Bash command would run, and reading
    hook.yaml when `settings` is not given (load_hook_settings)."""
    from ai_paladin.security.monitors import is_credential_path

    tool = call.get("tool_name", "")
    ti = call.get("tool_input") or {}
    cwd = call.get("cwd") or os.environ.get("CLAUDE_PROJECT_DIR") or os.getcwd()
    workspace = os.environ.get("CLAUDE_PROJECT_DIR") or cwd
    session = str(call.get("session_id") or "unknown")

    if tool == "Bash":
        if settings is None:
            settings = load_hook_settings()
        _check_bash(str(ti.get("command", "")), cmds, pkgs, cred_globs,
                    cwd, os.path.realpath(workspace), session,
                    strict=bool(settings.get("shell_writes_enforce_allow")),
                    scripts_env=bool(settings.get("scripts_may_read_env_files")))
        return

    paths = [ti.get(k) for k in ("file_path", "notebook_path", "path")
             if ti.get(k)]
    writes = tool in WRITE_TOOLS
    if tool == "WebFetch":
        url = str(ti.get("url", ""))
        if url.lower().startswith("file:"):      # a local file, by URL
            paths = [re.sub(r"^file:(//[^/]*)?", "", url, flags=re.I)]
    elif tool.startswith("mcp__"):
        # An MCP server's tool: any argument that names a file is checked
        # like Read's path; a tool whose name says it writes, like Write's.
        paths = _mcp_paths(ti)
        writes = bool(_MCP_WRITE_TOOL.search(tool.split("__")[-1]))
    for p in paths:
        real = _real(p, cwd)
        if is_credential_path(real, cred_globs) or is_credential_path(p, cred_globs):
            raise Refused("credential-path-access", "%s is a credential path" % p)
    if tool == "Glob" and _CRED_IN_SHELL.search(" " + str(ti.get("pattern", ""))):
        raise Refused("credential-path-access", "glob pattern targets a "
                      "credential location")
    if writes:
        for p in paths:
            real = _real(p, cwd)
            if _protected(real):
                raise Refused("hook-tamper", "%s is one of AI-Paladin's policy, "
                              "settings or log files, or Claude Code's "
                              "settings - only a person may edit it" % p)
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
                 ti.get("pattern") or ti.get("url") or ti.get("query") or
                 ti.get("description") or "")[:300]
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

# Claude Code calls the hook only for tools this matches (a regex). Beyond the
# file and shell tools: WebFetch / WebSearch, Task / Agent (subagents) and
# every MCP tool, so each is logged, counts toward fence-probing, stops when
# a session is paused, and has its paths checked. An install made before
# this list grew keeps its old matcher until `--install` is run again.
MATCHER = ("Bash|Write|Edit|MultiEdit|NotebookEdit|Read|Grep|Glob"
           "|WebFetch|WebSearch|Task|Agent|mcp__.*")


def settings_file(user: bool) -> str:
    if user:
        return os.path.join(os.path.expanduser("~"), ".claude", "settings.json")
    root = os.environ.get("CLAUDE_PROJECT_DIR") or os.getcwd()
    return os.path.join(root, ".claude", "settings.local.json")


def hook_command(settings_path: str) -> str:
    """
    The shell line Claude Code runs for every tool call.

      exit 0  the hook allowed the call          -> allowed
      exit 2  the hook refused it, with a reason -> refused
      other   the hook could not run at all      -> refused, AND an
              explanation: most likely AI-Paladin was removed without
              `--uninstall` first, so the message says how to recover.

    Claude Code only blocks on exit 2; any other failure would let the call
    through, so a hook that cannot start must still exit 2.
    """
    from ai_paladin import paths as ap
    wrapper = os.path.join(ap.BASE, "hooks", "pre_tool_use.py")
    help_msg = ("AI-Paladin's Claude Code hook could not run - was AI-Paladin "
                "removed without 'ai-paladin-hook --uninstall' first? Every "
                "tool call is refused until this is fixed. In an ordinary "
                "terminal, delete the pre_tool_use.py entry under "
                "hooks.PreToolUse in %s (or run: python3 %s --uninstall)."
                % (settings_path, wrapper))
    # The file test comes first: python itself exits 2 when the script is
    # missing, which would otherwise look like a deliberate refusal.
    q_py, q_wrap, q_msg = (shlex.quote(sys.executable), shlex.quote(wrapper),
                           shlex.quote(help_msg))
    return ("[ -f %s ] || { echo %s >&2; exit 2; }; %s %s; r=$?; "
            "[ $r = 0 ] && exit 0; [ $r = 2 ] || echo %s >&2; exit 2"
            % (q_wrap, q_msg, q_py, q_wrap, q_msg))


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


# Every settings file --install has written to, so that uninstalling can find
# all of them - not just this project and ~/.claude. Lives in the config
# folder, which the hook-tamper rule keeps agents out of.
REGISTRY = "hook_installs.json"


def _registry_path() -> str:
    from ai_paladin import paths as ap
    return os.path.join(ap.CONFIG_DIR, REGISTRY)


def registered() -> list:
    try:
        with open(_registry_path(), "r", encoding="utf-8") as fh:
            data = json.load(fh)
        return [str(p) for p in data.get("settings_files", [])]
    except (OSError, ValueError, AttributeError):
        return []


def _set_registry(files: list):
    p = _registry_path()
    os.makedirs(os.path.dirname(p), exist_ok=True)
    tmp = p + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump({"settings_files": sorted(set(files))}, fh, indent=2)
        fh.write("\n")
    os.replace(tmp, p)


def _has_ours(path: str) -> bool:
    pre = (_read_settings(path).get("hooks") or {}).get("PreToolUse") or []
    return any(isinstance(e, dict) and _is_ours(e) for e in pre)


def _remove_from(path: str) -> bool:
    """Remove our entry from one settings file. True if one was removed.
    Raises OSError/ValueError if the file cannot be read."""
    data = _read_settings(path)
    pre = (data.get("hooks") or {}).get("PreToolUse") or []
    kept = [e for e in pre if not (isinstance(e, dict) and _is_ours(e))]
    if len(kept) == len(pre):
        return False
    if kept:
        data["hooks"]["PreToolUse"] = kept
    else:
        del data["hooks"]["PreToolUse"]
        if not data["hooks"]:
            del data["hooks"]
    _write_settings(path, data)
    _log({"ts": datetime.now(timezone.utc).isoformat(), "kind": "hook",
          "decision": "uninstalled", "detail": path})
    return True


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
                "hooks": [{"type": "command", "command": hook_command(path)}]})
    _write_settings(path, data)
    _set_registry(registered() + [path])
    _log({"ts": datetime.now(timezone.utc).isoformat(), "kind": "hook",
          "decision": "installed", "detail": path})
    print("installed in %s\nClaude Code picks it up in new sessions.\n\n"
          "To turn it off:  ai-paladin-hook --uninstall%s\n"
          "To remove AI-Paladin entirely:  ai-paladin uninstall  (removes the "
          "hook everywhere first)\n"
          "Do not use a plain pip uninstall while the hook is installed, or "
          "Claude Code will refuse every tool call until the entry is removed."
          % (path, " --user" if user else ""))
    return 0


def uninstall(user: bool) -> int:
    path = settings_file(user)
    try:
        removed = _remove_from(path)
    except (OSError, ValueError) as exc:
        print("not changed - cannot read %s: %s" % (path, exc), file=sys.stderr)
        return 1
    _set_registry([p for p in registered() if p != path])
    print(("removed from %s" if removed else "not installed in %s") % path)
    return 0


def candidates() -> list:
    """Every settings file the hook could be in: recorded installs, this
    project, and ~/.claude."""
    seen, out = set(), []
    for p in registered() + [settings_file(False), settings_file(True)]:
        if p not in seen:
            seen.add(p)
            out.append(p)
    return out


def uninstall_all() -> tuple:
    """Remove the hook from every candidate. Returns (removed, failed), where
    failed is [(path, error)] for files that exist but cannot be read."""
    removed, failed = [], []
    for p in candidates():
        if not os.path.exists(p):
            continue
        try:
            if _remove_from(p):
                removed.append(p)
        except (OSError, ValueError) as exc:
            failed.append((p, str(exc)))
    _set_registry([p for p, _ in failed])
    return removed, failed


def where_installed() -> list:
    out = []
    for p in candidates():
        try:
            if os.path.exists(p) and _has_ours(p):
                out.append(p)
        except (OSError, ValueError):
            continue
    return out


def main(argv=None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if argv[:2] == ["--uninstall", "--all"] and len(argv) == 2:
        removed, failed = uninstall_all()
        for p in removed:
            print("removed from %s" % p)
        for p, err in failed:
            print("NOT removed - cannot read %s: %s" % (p, err), file=sys.stderr)
        if not removed and not failed:
            print("not installed anywhere AI-Paladin knows of")
        return 1 if failed else 0
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
                                     if places else "nowhere AI-Paladin "
                                     "knows of - run --install"))
        try:
            strict = load_hook_settings()["shell_writes_enforce_allow"]
            print("shell writes   %s" % (
                "write_scope deny + allow (shell_writes_enforce_allow: true)"
                if strict else "write_scope deny only (default)"))
            print("script .env    %s" % (
                "script files may name .env files (scripts_may_read_env_files: true)"
                if load_hook_settings()["scripts_may_read_env_files"]
                else "refused (default)"))
        except (OSError, ValueError) as exc:
            print("shell writes   hook.yaml unreadable - every call is "
                  "refused: %s" % exc)
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
              "[--user | --all] | --release SESSION | --status]",
              file=sys.stderr)
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
