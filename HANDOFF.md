# Handoff

The current work queue for ℂacheℝefresh's AI-Paladin, so any tool
(Claude Code, a Grok Bot, or a person) can pick up the next step.
Shared conventions are in [AGENTS.md](AGENTS.md). Update this file
when the queue changes.

Last updated: 2026-11-28, America/New_York.

Agents do not merge pull requests and do not publish packages. Rob
reviews and merges, and only Rob uploads to TestPyPI, PyPI, a PPA or
the VS Code Marketplace.

## Current state

- Repository: `https://github.com/cacherefresh/AI-Paladin`
- Default branch: `sanctuary`.
- Integration branch for this work: `feature/distribution-init`
  (protected). New work PRs into this branch until Rob creates
  `DEVELOPMENT`.
- Snapshot branch: `feature/distribution-init-snapshot`, frozen at
  `cbc9355` ("Safe uninstall: hook removed everywhere before the
  package"), taken so a later PR that breaks working code can be
  compared against it. Do not treat it as the tip of distribution
  work.
- Open PR: [#10](https://github.com/cacherefresh/AI-Paladin/pull/10),
  branch `feature/versioning-v0.3` into `feature/distribution-init`.
  It adds the root `VERSION` file (0.3.0), moves the pitch decks and
  the configuration manual to
  `ai-paladin/HUMAN_C_SUITE_DOCUMENTATION/` with `latest/` plus frozen
  prior versions, and the notes in `AGENTS.md`, `CLAUDE.md` and this
  file. Nothing from this PR has been merged yet.
- Merged into `feature/distribution-init`:
  [PR #8](https://github.com/cacherefresh/AI-Paladin/pull/8)
  (hook hardening, 2026-11-28) and
  [PR #9](https://github.com/cacherefresh/AI-Paladin/pull/9)
  (uninstaller, 2026-11-28).
- [PR #4](https://github.com/cacherefresh/AI-Paladin/pull/4) is
  do-not-merge. Leave it alone.
- Branch names for new work: `feature/...` or `bugfix/...` only. Rob
  always merges, using the ruleset bypass checkbox when required.

## Work queue (in order)

### (a) Build the v0.3.0 configuration manual PDF

This is the next step, and the reason to run commands on a machine
where Chrome finishes (headless Chrome hung in the environment that
prepared PR #10, even on a one-line HTML file).

The HTML is already in the tree. The PDF is not.

**Prerequisites**

- Google Chrome or Chromium. The script looks on `PATH` for
  `google-chrome`, `google-chrome-stable`, `chromium` and
  `chromium-browser`, and also for the usual macOS app paths
  (`/Applications/Google Chrome.app/Contents/MacOS/Google Chrome` and
  the Chromium equivalent).
- Optional: `pdfinfo` (poppler-utils) so the script can print a page
  count. The PDF is still written without it.
- Optional: `timeout` (GNU coreutils). On macOS the script still
  runs Chrome if `timeout` is not installed.
- No extra fonts to install. The HTML uses the system font stack and
  does not fetch webfonts. Printing is a local `file://` load; no
  network is required.

**Safe command (manual only; does not touch a pitch deck)**

From the repository root, on `feature/versioning-v0.3` if PR #10 is
still open:

```bash
ai-paladin/HUMAN_C_SUITE_DOCUMENTATION/build_pdfs.sh --manual
```

`--manual` rebuilds only
`USER_CONFIG/latest/USER_CONFIG_DECK.html`. It will not write a
pitch-deck PDF. Do not pass a `PITCH_DECK/` path, and do not use a
plain `./build_pdfs.sh` if you want to be certain the deck is left
alone. (A plain run also keeps an existing `PITCH_DECK/latest` PDF,
but `--manual` is the invocation to use.)

**Expected output**

`ai-paladin/HUMAN_C_SUITE_DOCUMENTATION/USER_CONFIG/latest/USER_CONFIG_DECK.pdf`

**How to verify**

```bash
# The new PDF exists and has pages
pdfinfo ai-paladin/HUMAN_C_SUITE_DOCUMENTATION/USER_CONFIG/latest/USER_CONFIG_DECK.pdf
# Only the manual PDF should be new. Pitch decks must be unchanged:
git status -- ai-paladin/HUMAN_C_SUITE_DOCUMENTATION/
git diff --stat -- ai-paladin/HUMAN_C_SUITE_DOCUMENTATION/PITCH_DECK/
```

`PITCH_DECK/` must show no changes. If it does, discard those
changes; do not commit them. Pitch decks are never edited by agents.

**Commit and PR**

If PR #10 is still open, commit the PDF on `feature/versioning-v0.3`
and push to that branch (no new PR). If #10 has already merged, open
a new `feature/` branch from `feature/distribution-init` and a PR
into `feature/distribution-init`. Rob reviews and merges.

### (b) TestPyPI dry run

Do this after PR #10 (including the PDF, if you add it) is merged
into `feature/distribution-init`, and before merging distribution
into `sanctuary`. Only Rob can create the TestPyPI account and
upload. Agents must not upload and must not be given the token.

There is not yet a GitHub Actions release workflow in this
repository. Until there is, the dry run is a local build and a
manual upload.

1. Rob creates an account at https://test.pypi.org with two-factor
   authentication, and an API token from
   https://test.pypi.org/manage/account/token/.
2. From `feature/distribution-init`, on Rob's machine:

```bash
python3 -m pip install build twine
python3 -m build
python3 -m twine check dist/*
python3 -m twine upload --repository testpypi dist/*
```

3. In a clean virtual environment, install that upload and check the
   commands. PyYAML is pulled from the real PyPI index because it may
   not be on TestPyPI:

```bash
python3 -m venv /tmp/ai-paladin-testpypi
/tmp/ai-paladin-testpypi/bin/pip install \
  -i https://test.pypi.org/simple/ \
  --extra-index-url https://pypi.org/simple/ \
  ai-paladin==0.3.0
/tmp/ai-paladin-testpypi/bin/ai-paladin --version
/tmp/ai-paladin-testpypi/bin/ai-paladin --where
/tmp/ai-paladin-testpypi/bin/ai-paladin-hook --help
/tmp/ai-paladin-testpypi/bin/ai-paladin uninstall --dry-run
```

`--version` should print `ai-paladin 0.3.0`. `--where` should list
the shipped files. `uninstall --dry-run` should run without changing
anything (it may say there is nothing recorded if the hook was never
installed in that environment).

A later production PyPI release still needs the Trusted Publishing
workflow and the other **(Rob)** steps in `DISTRIBUTION/CHECKLIST.md`
section 3. That is not this step.

### (c) Merge `feature/distribution-init` into `sanctuary`

After the TestPyPI dry run looks good, Rob opens (or accepts) a PR
from `feature/distribution-init` into `sanctuary` and merges it
himself, using the bypass checkbox if the ruleset requires it. Bots
do not merge.

### (d) Rob creates the `DEVELOPMENT` branch

After distribution has merged into `sanctuary`, Rob creates
`DEVELOPMENT`. The branch ruleset will lock it automatically. Later
feature work PRs into `DEVELOPMENT`, which then flows into
`sanctuary`.

### (e) VS Code extension

One platform at a time: the pip package first (this distribution
branch), then the VS Code extension on its own `feature/` branch,
then the Ubuntu PPA. Remaining Marketplace work is listed in
`DISTRIBUTION/CHECKLIST.md` section 2 (icon, licence copy, local
`.vsix` install, Rob's publisher registration and publish). The
extension version in `vscode/ai-paladin/package.json` must keep
matching the root `VERSION` file (today 0.3.0).

### (f) Ubuntu PPA

After the VS Code work, add Debian packaging on its own `feature/`
branch. `debian/changelog` (or the same file under `packaging/`,
`DISTRIBUTION/` or `ubuntu/`) must match the root `VERSION` file.
`ai-paladin/tests/test_version.py` fails if they drift. Other steps
are in `DISTRIBUTION/CHECKLIST.md` section 5. Only Rob creates the
Launchpad account, signs the Code of Conduct, and uploads with
`dput`.

### (g) Required CI checks on the rulesets

After the merges above, Rob adds the four CI checks as required
status checks on the rulesets that protect `sanctuary`,
`feature/distribution-init`, and `DEVELOPMENT` once it exists:

- `tests (Python 3.12)`
- `tests (Python 3.13)`
- `wheel installs into a clean venv (Python 3.12)`
- `wheel installs into a clean venv (Python 3.13)`

Do not add these on web-os. Rob merges with the bypass checkbox
until the checks are in place, and can still bypass afterwards as
repository admin.

### (h) Re-run `ai-paladin-hook --install` where the hook is installed

This can be done now; it does not have to wait for (a)-(g). PRs #8
and #9 already changed install recording and hook behaviour, and
asked for a re-install so fingerprints are stored. On each machine
where the hook was installed:

```bash
ai-paladin-hook --install            # this project
ai-paladin-hook --install --user     # if it was installed for every project
ai-paladin-hook --status
```

## How to run the tests

From the repository root, in a virtual environment (Python 3.12 or
3.13):

```bash
python3 -m venv /tmp/ai-paladin-tests
/tmp/ai-paladin-tests/bin/pip install -e .
cd ai-paladin
/tmp/ai-paladin-tests/bin/python -m unittest discover -s tests -v
```

As of 2026-11-28, on `feature/versioning-v0.3`, that suite is **172
passed, 2 skipped**. The skips are:

- `test_debian_changelog_matches_when_present`, because there is no
  Ubuntu changelog in the tree yet.
- `test_wheel_installs_and_boots_in_a_clean_venv`, unless you set
  `AI_PALADIN_WHEEL_TEST=1`.

The two skips should remain until Debian packaging exists and until
you opt into the wheel job. A new test on this branch would raise
the passed count.

To also run the clean-venv wheel install (CI does this on Python
3.12 and 3.13):

```bash
cd ai-paladin
AI_PALADIN_WHEEL_TEST=1 /tmp/ai-paladin-tests/bin/python \
  -m unittest tests.test_wheel_install -v
```

CI workflows are in `.github/workflows/ci.yml`, triggered on
`feature/**` and on pull requests.
