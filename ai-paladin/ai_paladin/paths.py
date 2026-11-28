"""
Where AI-Paladin's files live.

Three places, never mixed:

  BASE        shipped, read-only. In a source checkout, the project folder
              (ai-paladin/); in an installed wheel, ai_paladin/_shipped/.
              Holds the defaults: router/, agents/, models/, security/,
              ui/, demo/, hooks/. Nothing here is written at run time.
  CONFIG_DIR  this user's settings and overrides. Written by the dashboard
              (local_models.yaml) and by the user (keywords.yaml overlay,
              replacement policy.yaml, web_accounts.yaml).
              Default ~/.config/ai-paladin/
  LOG_DIR     run-time state: the audit logs.
              Default ~/.local/state/ai-paladin/logs/

The defaults follow the XDG base-directory convention. AI_PALADIN_CONFIG_DIR
and AI_PALADIN_LOG_DIR override them; `ai-paladin --demo` (and run_demo.sh)
point them at ai-paladin/config and ai-paladin/logs so the demo keeps
everything inside the repo.

These are read once, at import. Set the environment before importing any
ai_paladin module - ai_paladin.cli does this for you.
"""

import os

_PKG = os.path.dirname(os.path.abspath(__file__))
# An installed wheel carries the shipped defaults inside the package, under
# ai_paladin/_shipped/ (pyproject.toml maps ai-paladin/ there). A source
# checkout or an editable install has no such folder and reads them from
# ai-paladin/ itself.
_BUNDLED = os.path.join(_PKG, "_shipped")
BASE = (_BUNDLED if os.path.isfile(os.path.join(_BUNDLED, "router", "policy.yaml"))
        else os.path.dirname(_PKG))


def _from_env(var: str, default: str) -> str:
    value = os.environ.get(var)
    return os.path.abspath(os.path.expanduser(value)) if value else default


_HOME = os.path.expanduser("~")
_XDG_CONFIG = os.environ.get("XDG_CONFIG_HOME") or os.path.join(_HOME, ".config")
_XDG_STATE = (os.environ.get("XDG_STATE_HOME")
              or os.path.join(_HOME, ".local", "state"))

CONFIG_DIR = _from_env("AI_PALADIN_CONFIG_DIR",
                       os.path.join(_XDG_CONFIG, "ai-paladin"))
LOG_DIR = _from_env("AI_PALADIN_LOG_DIR",
                    os.path.join(_XDG_STATE, "ai-paladin", "logs"))


def shipped(*parts: str) -> str:
    """A file that ships with AI-Paladin. Read it; never write it."""
    return os.path.join(BASE, *parts)


def user_config(name: str) -> str:
    """A file in this user's config folder. May not exist."""
    return os.path.join(CONFIG_DIR, name)


def log_file(name: str) -> str:
    return os.path.join(LOG_DIR, name)
