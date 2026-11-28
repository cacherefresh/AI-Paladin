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
- Default / release branch: `sanctuary` (head `d53c3c3`, "Merge pull
  request #4 from cacherefresh/feature/distribution-init").
  [PR #13](https://github.com/cacherefresh/AI-Paladin/pull/13) put
  `release.yml` on sanctuary so the workflow can be started;
  [PR #4](https://github.com/cacherefresh/AI-Paladin/pull/4) then
  merged the distribution work, after the TestPyPI dry run.
- Integration branch: `development` (lowercase), created by Rob on
  2026-11-28 from sanctuary. It is currently at the same commit as
  sanctuary (`d53c3c3`). New work is cut from `development`. Bots
  and Claude Code open PRs into `development` only. Rob reviews and
  merges those PRs, and only Rob promotes `development` into
  `sanctuary`.
- Snapshot branch: `feature/distribution-init-snapshot`, frozen at
  `cbc9355` ("Safe uninstall: hook removed everywhere before the
  package"), taken so a later PR that breaks working code can be
  compared against it. Do not treat it as the tip of current work.
- Historical: distribution work lived on `feature/distribution-init`
  and was merged into sanctuary via PR #4 on 2026-11-28. That
  integration branch is gone on origin. PRs merged into it earlier
  the same day were
  [PR #8](https://github.com/cacherefresh/AI-Paladin/pull/8)
  (hook hardening),
  [PR #9](https://github.com/cacherefresh/AI-Paladin/pull/9)
  (uninstaller), and
  [PR #10](https://github.com/cacherefresh/AI-Paladin/pull/10)
  (versioning v0.3.0, docs consolidation, v0.3.0 manual PDF named
  `USER_CONFIG_MANUAL`).
- Branch names for new work: `feature/...` or `bugfix/...` only,
  cut from `development`. Rob always merges, using the ruleset
  bypass checkbox when required.
- Version: `0.3.0` (root `VERSION` file).
- TestPyPI: `ai-paladin` 0.3.0 is at
  https://test.pypi.org/project/ai-paladin/ . Production PyPI has
  not been published yet.

## Work queue (in order)

### (a) Build the v0.3.0 configuration manual PDF

**Done 2026-11-28.** The PDF was built on `feature/versioning-v0.3`
(16 pages, A4 landscape) and merged in PR #10. Slide 15 ran off the
page, so its layout was changed (CSS and card order only, no
wording). `PITCH_DECK/` was not touched. The files in `latest/` are
named `USER_CONFIG_MANUAL.html` and `USER_CONFIG_MANUAL.pdf`. Frozen
`v0.2/` still uses `USER_CONFIG_DECK`.

The steps below stay as the procedure for the next rebuild.

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

From the repository root, on a `feature/` branch off `development`:

```bash
ai-paladin/HUMAN_C_SUITE_DOCUMENTATION/build_pdfs.sh --manual
```

`--manual` rebuilds only
`USER_CONFIG/latest/USER_CONFIG_MANUAL.html`. It will not write a
pitch-deck PDF. Do not pass a `PITCH_DECK/` path, and do not use a
plain `./build_pdfs.sh` if you want to be certain the deck is left
alone. (A plain run also keeps an existing `PITCH_DECK/latest` PDF,
but `--manual` is the invocation to use.)

**Expected output**

`ai-paladin/HUMAN_C_SUITE_DOCUMENTATION/USER_CONFIG/latest/USER_CONFIG_MANUAL.pdf`

**How to verify**

```bash
# The new PDF exists and has pages
pdfinfo ai-paladin/HUMAN_C_SUITE_DOCUMENTATION/USER_CONFIG/latest/USER_CONFIG_MANUAL.pdf
# Only the manual PDF should be new. Pitch decks must be unchanged:
git status -- ai-paladin/HUMAN_C_SUITE_DOCUMENTATION/
git diff --stat -- ai-paladin/HUMAN_C_SUITE_DOCUMENTATION/PITCH_DECK/
```

`PITCH_DECK/` must show no changes. If it does, discard those
changes; do not commit them. Pitch decks are never edited by agents.

**Commit and PR**

Open a new `feature/` branch from `development` and a PR into
`development`. Rob reviews and merges.

### (b) TestPyPI dry run

**Done 2026-11-28.** GitHub Actions
[run 46163165656](https://github.com/cacherefresh/AI-Paladin/actions/runs/46163165656)
published `ai-paladin` 0.3.0 (wheel and sdist) to TestPyPI. A clean
virtual environment install was verified: `ai-paladin --version`
printed `ai-paladin 0.3.0`, `--help` exited 0, and
`ai-paladin-hook --status` exited 0. The production PyPI job was
skipped, as intended.

The first `workflow_dispatch` attempt could not start until
`release.yml` existed on the default branch. PR #13 put that file
on sanctuary so the workflow could be registered. The Lead Engineer
GitHub App has no permission to start workflow runs, on purpose, so
only Rob starts a release from the Actions tab.

The click-by-click steps for a later TestPyPI upload (or a redo)
are in **`docs/RELEASING.md`**. TestPyPI will not accept a second
upload of version 0.3.0. If a redo is needed, do not change the
committed `VERSION` file (it must stay `X.Y.Z`). Re-dispatch with
`prerelease=rc1` to upload `0.3.0rc1` instead.

A later production PyPI release uses the same workflow on a `v0.3.0`
tag, after the `pypi` Trusted Publisher is registered, and waits for
Rob's approval on the `pypi` environment. That is not this step.

### (c) Merge `feature/distribution-init` into `sanctuary`

**Done 2026-11-28.** Rob retitled and merged
[PR #4](https://github.com/cacherefresh/AI-Paladin/pull/4) into
sanctuary after the TestPyPI dry run. sanctuary and `development`
are at `d53c3c3`.

### (d) Rob creates the `development` branch

**Done 2026-11-28.** The branch is `development` (lowercase), cut
from sanctuary at `d53c3c3`. Later feature work PRs into
`development`, which then flows into `sanctuary` when Rob promotes
it. The earlier working name `DEVELOPMENT` (all caps) is not used.

### (e) VS Code extension

**This is the next step.** One platform at a time: the pip package
is on TestPyPI, then the VS Code extension on its own `feature/`
branch off `development`, then the Ubuntu PPA. Remaining
Marketplace work is listed in `DISTRIBUTION/CHECKLIST.md` section 2
(icon, licence copy, local `.vsix` install, Rob's publisher
registration and publish). The extension version in
`vscode/ai-paladin/package.json` must keep matching the root
`VERSION` file (today 0.3.0).

### (f) Ubuntu PPA

After the VS Code work, add Debian packaging on its own `feature/`
branch off `development`. `debian/changelog` (or the same file under
`packaging/`, `DISTRIBUTION/` or `ubuntu/`) must match the root
`VERSION` file. `ai-paladin/tests/test_version.py` fails if they
drift. Other steps are in `DISTRIBUTION/CHECKLIST.md` section 5.
Only Rob creates the Launchpad account, signs the Code of Conduct,
and uploads with `dput`.

### (g) Required CI checks on the rulesets

After the merges above, Rob adds the four CI checks as required
status checks on the rulesets that protect `sanctuary` and
`development`:

- `tests (Python 3.12)`
- `tests (Python 3.13)`
- `wheel installs into a clean venv (Python 3.12)`
- `wheel installs into a clean venv (Python 3.13)`

Do not add these on web-os. Rob merges with the bypass checkbox
until the checks are in place, and can still bypass afterwards as
repository admin.

### (h) Re-run `ai-paladin-hook --install` where the hook is installed

This can be done now; it does not have to wait for (e)-(g). PRs #8
and #9 already changed install recording and hook behaviour, and
asked for a re-install so fingerprints are stored. On each machine
where the hook was installed:

```bash
ai-paladin-hook --install            # this project
ai-paladin-hook --install --user     # if it was installed for every project
ai-paladin-hook --status
```

### (i) Production PyPI release

After the `pypi` Trusted Publisher is registered (a PyPI account
with 2FA, then a pending publisher with environment `pypi`), Rob
publishes 0.3.0 from sanctuary by pushing a `v0.3.0` tag. The
Release workflow waits for his approval on the `pypi` environment.
Steps are in `docs/RELEASING.md`. Do not pass `prerelease` on a tag.

## How to run the tests

From the repository root, in a virtual environment (Python 3.12 or
3.13):

```bash
python3 -m venv /tmp/ai-paladin-tests
/tmp/ai-paladin-tests/bin/pip install -e .
cd ai-paladin
/tmp/ai-paladin-tests/bin/python -m unittest discover -s tests -v
```

As of 2026-11-28, on `feature/development-branch-docs`, that
suite is **184 passed, 2 skipped** (186 tests run). The skips are:

- `test_debian_changelog_matches_when_present`, because there is no
  Ubuntu changelog in the tree yet.
- `test_wheel_installs_and_boots_in_a_clean_venv`, unless you set
  `AI_PALADIN_WHEEL_TEST=1`.

The two skips should remain until Debian packaging exists and until
you opt into the wheel job. The passed count is one higher than the
previous suite because of an added dispatch runbook test. Confirm
the count after you run the suite, and correct this paragraph if it
has drifted.

To also run the clean-venv wheel install (CI does this on Python
3.12 and 3.13):

```bash
cd ai-paladin
AI_PALADIN_WHEEL_TEST=1 /tmp/ai-paladin-tests/bin/python   -m unittest tests.test_wheel_install -v
```

CI workflows are in `.github/workflows/ci.yml`, triggered on
`sanctuary`, `development`, `feature/**`, `bugfix/**`,
and on pull requests.
