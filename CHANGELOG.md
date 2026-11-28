# Changelog

Software changes in ℂacheℝefresh's AI-Paladin. The version in the
repo-root `VERSION` file is shared by the pip package, the VS Code
extension and, when it exists, the Ubuntu package.

Document-set changes (pitch deck, configuration manual) are in
`CHANGES.md` under each set in
`ai-paladin/HUMAN_C_SUITE_DOCUMENTATION/`.

## 0.3.0 - 2026-11-28

The distribution release. First version intended to ship as a pip
package. Numbered 0.3.0 so it lines up with the pitch-deck and manual
series (v0.1, v0.2, and the v0.3 manual).

- Settings layers, the `ai-paladin` command, a user configuration
  folder and the first configuration manual (2026-11-24).
- Wheel packaging: shipped defaults travel as `ai_paladin/_shipped/`
  package data; clean-venv wheel install in CI on Python 3.12 and 3.13
  (PR #6, 2026-11-27 and 2026-11-28).
- Router API: Host allowlist, Origin check, JSON only, per-start token
  (PR #6).
- Known PreToolUse hook bypasses pinned as expected failures (PR #6).
- Project folder renamed from `ai-org-router/` to `ai-paladin/` (PR #7,
  2026-11-28).
- PreToolUse hook hardened (PR #8, 2026-11-28): unwraps nested shells;
  resolves quoting, variables and symlinks; checks files that shell
  commands and agent-written scripts write; covers WebFetch, WebSearch,
  Task/Agent and MCP tools; refuses edits to AI-Paladin policy files
  and to the hook's own code; opt-in `hook.yaml` settings
  `shell_writes_enforce_allow` and `scripts_may_read_env_files`.
  Documented as a hardened guardrail, not a security boundary.
- Uninstaller (PR #9, 2026-11-28): `ai-paladin-hook --install` records
  each hook entry it adds; `ai-paladin uninstall` lists them, asks
  "Do you want me to remove the hooks I added outside of python?(Y/n)",
  and removes only unchanged entries it recorded. It does not run pip.
- One `VERSION` file at the repository root. Documentation lives only
  under `ai-paladin/HUMAN_C_SUITE_DOCUMENTATION/`, with `latest/` and
  frozen prior versions. The v0.3.0 configuration manual files are
  `USER_CONFIG_MANUAL.html` and `USER_CONFIG_MANUAL.pdf`; frozen
  earlier versions keep the `USER_CONFIG_DECK` names.
- Agent conventions and the work queue live at the repo root in
  `AGENTS.md`, `CLAUDE.md` and `HANDOFF.md`, outside the pip package.
- Pip release workflow (`.github/workflows/release.yml`) uses PyPI
  Trusted Publishing. The TestPyPI dry-run and production steps are
  in `docs/RELEASING.md`.

## 0.2.0 - 2026-11-22

- Multiple on-prem models, with weights kept per machine and gitignored
  (PR #3).
- On-prem internet-access modes: isolated, read-only (RAG) and
  read/write (bot), including HTTP method enforcement (PR #3).

## 0.1.0 - 2026-08-14

- Initial repository, licence and scaffolding (PR #1, 2026-07-15).
- First working MVP: on-prem router, gates, demo UI and pitch deck
  v0.1 (PR #2; MVP commit 2026-08-14, merged 2026-11-18).
