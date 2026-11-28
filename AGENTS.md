# AGENTS.md

Conventions for coding agents working in this repository. Read this before
creating files.

## Who works on this repo

This file lives at the repository root, outside the pip package. It is
not shipped in the wheel or the sdist. The same is true of `CLAUDE.md`
and `HANDOFF.md`.

Two kinds of tools work on this code:

- **Claude Code**, run by Rob on his own machine.
- **Grok Bot** agents, including the AI Paladin Lead Engineer bot,
  which acts on GitHub as the App `ai-paladin-lead-engineer-bot`.
  Other Grok Bots may also work in this repository.

They follow the same rules:

- Bots only create branches named `feature/...` or `bugfix/...`, cut
  from `development`, and only open pull requests into `development`.
  Rob always reviews and merges. Bots never merge, never push to
  `sanctuary` or `development` directly, and they never publish to
  PyPI, TestPyPI, a PPA or the VS Code Marketplace. How Rob publishes
  the pip package is in `docs/RELEASING.md`.
- Do not edit `router/keywords.yaml`, `router/policy.yaml` or
  `security/policies/` to make a test pass. See "The gates are data,
  not prose" below.
- Pitch decks are never changed by agents. See "Documentation home
  and frozen versions" below.
- The project version comes from the root `VERSION` file. pip, the
  VS Code extension and Ubuntu must match it. See "Versioning" below.
- The current work queue, so any tool can pick up where the last one
  stopped, is in **`HANDOFF.md`** at the repository root (committed).
  Update that file when the queue changes. Session scratch still goes
  in `TEMPORARY/TEMP_NOTES.md` (gitignored).
- While the PreToolUse hook is installed, it refuses agent edits to
  the hook's own code (`ai_paladin/hook.py` and the modules it runs,
  `hooks/pre_tool_use.py`, the installed `ai-paladin-hook` command)
  and to the policy files. Rob edits those files himself, or runs
  without the hook.

Claude Code reads `CLAUDE.md`, which points here.

## Branches

The default branch is `sanctuary`. It is the release branch.

`development` (lowercase) is branched off `sanctuary`. Day-to-day
work happens here.

New work is cut from `development` onto a `feature/...` or
`bugfix/...` branch. Bots and Claude Code open pull requests into
`development` only. Rob reviews and merges those PRs. Only Rob
promotes `development` into `sanctuary`.

## Scratch notes go in `TEMPORARY/TEMP_NOTES.md`

Session-specific working notes - staging plans, window layouts for a demo,
"what I was about to do next", open questions - belong in
**`TEMPORARY/TEMP_NOTES.md`**, which is gitignored.

Do **not** scatter `NOTES.md`, `TODO.md`, `PLAN.md`, `SCRATCH.md` or dated
variants through the tree. Those files are context a future session has
to read and weigh, and most of them are stale within days. Session
scratch has one known location, ignored by git:
`TEMPORARY/TEMP_NOTES.md`. The one committed handoff file is
`HANDOFF.md`.

**The rule in one line:** if it will be false next week, it goes in
`TEMPORARY/TEMP_NOTES.md`. If it will still be true, it goes in `docs/` and is
committed.

Concretely:

| Content | Where |
|---|---|
| A reusable runbook or procedure | `ai-paladin/docs/` - committed |
| How to publish the pip package | `docs/RELEASING.md` (repo root, outside the package) - committed |
| Brand logo and favicons | `assets/logo/` (repo root, outside the package) - committed |
| Design intent, roadmap, honest limits | `ai-paladin/docs/ROADMAP.md` - committed |
| What a module does and why | its own `README.md` - committed |
| This session's staging notes, todo, layout | `TEMPORARY/TEMP_NOTES.md` - ignored |
| Current work queue and handoff between tools | `HANDOFF.md` (repo root) - committed |

If a scratch note turns out to be durable, move it into `docs/` and delete it
from the scratch file rather than leaving both.

## The gates are data, not prose

`router/keywords.yaml`, `router/policy.yaml`, the demo overlay
`config/keywords.yaml`, `security/policies/` and `security/monitors/` are
enforcement, not documentation. Do not edit them to make a test pass or a
demo read better, and never add a rule that a model is asked to honour rather
than a router is made to enforce. A gate a model can talk its way past is not
a gate.

The shipped `router/keywords.yaml` is deliberately small and generic;
demo-only terms belong in the demo overlay, never in the defaults.

`security/policies/` and most of `security/monitors/` are enforced by the
Claude Code hook (`ai_paladin/hook.py`), and only when it is installed. Every
rule in `behavioral_rules.yaml` states on its `enforced:` line where it is
enforced, or that it is not. Keep those lines true when you change either
side.

## Do not overstate enforcement

This repository sells containment, so its own claims are held to the standard
it sells. `ai_paladin/security/egress_guard.py` is a **process-level** guard, not a host
firewall and not an air gap. Any wording that implies otherwise - in code
comments, docs, the demo runbook or the pitch deck - is a defect. When
describing what is enforced, state the scope and the limit in the same
sentence.

## Brand name: ℂacheℝefresh, with an ASCII fallback

Write the publisher's name as **ℂacheℝefresh** (U+2102 DOUBLE-STRUCK CAPITAL C,
U+211D DOUBLE-STRUCK CAPITAL R) everywhere a person reads it: docs, READMEs,
display names, UI text, the pitch deck, marketplace listings. The VS Code
extension's display name is **ℂacheℝefresh's AI-Paladin**.

Fall back to plain ASCII only where the context cannot take it:

| Context | Write |
|---|---|
| Prose, display names, UI, deck, marketplace listing text | `ℂacheℝefresh` |
| Package names, publisher IDs, GitHub org, URLs, file names | `cacherefresh` |
| Code identifiers, YAML keys, env vars | `cacherefresh` / `CACHEREFRESH` - never the symbols; Python's NFKC folds `ℝ` to `R` |
| Copyright and legal notices | `ℂacheℝefresh (CacheRefresh)` - branded, plus the ASCII form so the notice stays searchable |
| Git commit authorship, plain-ASCII logs, headers | `CacheRefresh` |

Registries reject non-ASCII names on purpose - look-alike characters are a
package-spoofing attack - so the symbols never go in an identifier. Where a
display name uses them, also list `cacherefresh` as a search keyword so
people who type it in ASCII still find us.

## Versioning

The file `VERSION` at the repository root is the single source for the
project version (currently 0.3.0; distribution ships as v0.3). pip, the
VS Code extension and the Ubuntu package must all use that same number.

- `pyproject.toml` reads `VERSION` (`[tool.setuptools.dynamic] version = {file = "VERSION"}`).
- `ai_paladin.__version__` reads the same file in a checkout, or the
  installed package metadata in a wheel.
- `vscode/ai-paladin/package.json` `"version"` must be edited to match
  when `VERSION` changes.
- Ubuntu/Debian packaging is not in the tree yet. When it is added, the
  first entry in `debian/changelog` (or `packaging/debian/changelog`,
  `DISTRIBUTION/debian/changelog`, `ubuntu/debian/changelog`) must match
  `VERSION`.
- `ai-paladin/tests/test_version.py` fails if any of the above drift.

Do not hard-code a second project version in `pyproject.toml` or
`ai_paladin/__init__.py`.

Software changes go in the root `CHANGELOG.md`.

## Documentation home and frozen versions

All human-facing decks and manuals live in **one** place:

`ai-paladin/HUMAN_C_SUITE_DOCUMENTATION/`

with two subfolders, `PITCH_DECK/` and `USER_CONFIG/`. Each has:

- `latest/` — the newest version itself, not a copy. A `latest/VERSION`
  marker states which version it is (the pitch deck's latest is v0.2
  until a v0.3 deck is written; the configuration manual's latest is
  v0.3.0).
- Frozen prior-version folders (`v0.1/`, `v0.2/`, …) — never edited.
- `CHANGES.md` — what changed as versions increment.

There is exactly one copy of each version. Do not keep a second tree
under `USER_CONFIG/` at the repo root, or a `v0.2/` folder alongside
`latest/` while latest is still v0.2.

When incrementing a document set:

1. `git mv latest vX.Y` (the version that *was* current).
2. Create a new `latest/` with the new files and a `latest/VERSION` marker.
3. Add an entry to that set's `CHANGES.md` and, for a software version
   bump, to the root `CHANGELOG.md` and the root `VERSION` file. Update
   `vscode/ai-paladin/package.json` to match. Run the version test.

From v0.3.0 on, the configuration manual files in `USER_CONFIG/latest/`
are named `USER_CONFIG_MANUAL.html` and `USER_CONFIG_MANUAL.pdf`.
Frozen earlier versions keep the older `USER_CONFIG_DECK` filenames
and must not be renamed.

Rebuild the configuration manual PDF with
`ai-paladin/HUMAN_C_SUITE_DOCUMENTATION/build_pdfs.sh --manual`.
That invocation does not touch a pitch deck. Frozen PDFs are never
overwritten.

**Pitch decks are never edited by agents.** Do not change the HTML, PDF
or screenshots of any pitch deck version, including the one in `latest/`.
A new pitch deck is a new version folder, created only when Rob asks for
one.
