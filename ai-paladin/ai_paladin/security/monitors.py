"""
security/monitors/behavioral_rules.yaml, as code.

Shared by the router (web tools, file reads) and the Claude Code hook
(ai_paladin/hook.py). Each rule in the YAML says under `enforced:` which of
the two enforces it and how; this module only supplies the parameters and
the path matching, so both enforcers read the same numbers.

Defaults below are used only if the YAML omits a value. They match the
shipped file, so a missing key never loosens a rule.
"""

import fnmatch
import os
from typing import List

from ai_paladin import config_layers

DEFAULT_MAX_BLOCKED = 3
DEFAULT_MAX_WRITES = 200
DEFAULT_WINDOW_S = 60
DEFAULT_CREDENTIAL_PATHS = ["**/.ssh/**", "**/.aws/**", "**/.env", "**/.env.*"]


def load_rules() -> dict:
    """{rule id: rule} from behavioral_rules.yaml (user copy if present)."""
    data, _ = config_layers.load_whole("behavioral_rules.yaml")
    return {r["id"]: r for r in data.get("rules", []) if "id" in r}


def _param(rules: dict, rule_id: str, key: str, default):
    value = (rules.get(rule_id) or {}).get(key, default)
    return default if value is None else value


def max_blocked(rules: dict = None) -> int:
    return int(_param(rules or load_rules(), "fence-probing", "max_blocked",
                      DEFAULT_MAX_BLOCKED))


def write_limits(rules: dict = None):
    rules = rules or load_rules()
    return (int(_param(rules, "mass-file-touch", "max_writes",
                       DEFAULT_MAX_WRITES)),
            float(_param(rules, "mass-file-touch", "window_s",
                         DEFAULT_WINDOW_S)))


def credential_globs(rules: dict = None) -> List[str]:
    return list(_param(rules or load_rules(), "credential-path-access",
                       "paths", DEFAULT_CREDENTIAL_PATHS))


def is_credential_path(path: str, globs: List[str] = None) -> bool:
    """
    True if `path` (relative or absolute, ~ allowed) is a credential file.
    Matched with and without a leading slash, so "**/.env" also catches a
    bare ".env" at the top of a corpus, and with a trailing slash, so the
    folder itself ("~/.aws") counts as well as the files in it.
    """
    globs = globs if globs is not None else credential_globs()
    p = os.path.expanduser(str(path)).replace(os.sep, "/")
    rooted = "/" + p.lstrip("/")
    candidates = {p, rooted, rooted.rstrip("/") + "/"}
    return any(fnmatch.fnmatch(c, g) for c in candidates for g in globs)
