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
- Default branch: `sanctuary` (head `502a078`, "Add YouTube demo
  section to README").
- Integration branch for this work: `feature/distribution-init`
  (protected, head `6fee477`). It is a clean fast-forward of
  sanctuary (35 commits on top of `502a078`). Rob rebased it onto
  sanctuary on 2026-11-28 so the YouTube README section is included.
  New work PRs into this branch until Rob creates `DEVELOPMENT`.
- Snapshot branch: `feature/distribution-init-snapshot`, frozen at
  `cbc9355` ("Safe uninstall: hook removed everywhere before the
  package"), taken so a later PR that breaks working code can be
  compared against it. Do not treat it as the tip of distribution
  work.
- Merged into `feature/distribution-init` on 2026-11-28:
  [PR #8](https://github.com/cacherefresh/AI-Paladin/pull/8)
  (hook hardening),
  [PR #9](https://github.com/cacherefresh/AI-Paladin/pull/9)
  (uninstaller), and
  [PR #10](https://github.com/cacherefresh/AI-Paladin/pull/10)
  (versioning v0.3.0, docs consolidation, v0.3.0 manual PDF named
  `USER_CONFIG_MANUAL`).
- Next step: the TestPyPI dry run (see (b) and
  `docs/RELEASING.md`), then a merge of
  `feature/distribution-init` into `sanctuary`. Rob confirmed
  2026-11-28 to do the dry run first. Do not open a sanctuary merge
  PR until that dry run is done. The release workflow is added on
  `feature/testpypi-release`; dispatch it from
  `feature/distribution-init` after that PR is merged.
- [PR #4](https://github.com/cacherefresh/AI-Paladin/pull/4) is
  do-not-merge. Leave it alone. It is already open from
  `feature/distribution-init` into `sanctuary` (head `6fee477`, base
  `502a078`), so it now contains the full distribution work. GitHub
  will not accept a second open PR with the same head and base. A
  later sanctuary merge will need a new branch, or Rob's decision on
  #4. Do not retitle, close, draft, or merge #4 unless Rob says so.
- Branch names for new work: `feature/...` or `bugfix/...` only. Rob
  always merges, using the ruleset bypass checkbox when required.
- Version: `0.3.0` (root `VERSION` file).

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

From the repository root, on a `feature/` branch off
`feature/distribution-init`:

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

Open a new `feature/` branch from `feature/distribution-init` and a
PR into `feature/distribution-init`. Rob reviews and merges.

### (b) TestPyPI dry run

**This is the next step.** PR #10 (including the v0.3.0 manual PDF)
is already merged into `feature/distribution-init`. Do this before
merging distribution into `sanctuary`. Only Rob can create the
TestPyPI account, the GitHub environments, and the Trusted
Publisher, and only Rob dispatches the upload. Agents must not
upload, must not create accounts, and must not be given a token.
The workflow uses Trusted Publishing (OIDC); there is no stored
API token.

The click-by-click steps are in **`docs/RELEASING.md`**. A short
summary:

1. Create a TestPyPI account at https://test.pypi.org and enable 2FA.
   A TestPyPI account is not a PyPI account.
2. In the GitHub repo, create environments named exactly `testpypi`
   and `pypi`. On `pypi`, add yourself as a required reviewer.
3. Add a pending Trusted Publisher at
   https://test.pypi.org/manage/account/publishing/:
   project `ai-paladin`, owner `cacherefresh`, repository
   `AI-Paladin`, workflow `release.yml`, environment `testpypi`.
4. After the release workflow PR has merged into
   `feature/distribution-init`, dispatch it from that branch
   (the file has to be on the branch that runs it):

```bash
gh workflow run release.yml \
  --repo cacherefresh/AI-Paladin \
  --ref feature/distribution-init \
  -f target=testpypi
```

   The Actions tab may not list this workflow until it also exists
   on `sanctuary`, so `gh` is the reliable way to start it now.

5. In a clean virtual environment, install that upload and check the
   commands. PyYAML is pulled from the real PyPI index because it may
   not be on TestPyPI:

```bash
python3 -m venv /tmp/ai-paladin-testpypi
/tmp/ai-paladin-testpypi/bin/pip install \
  -i https://test.pypi.org/simple/ \
  --extra-index-url https://pypi.org/simple/ \
  ai-paladin==0.3.0
/tmp/ai-paladin-testpypi/bin/ai-paladin --version
/tmp/ai-paladin-testpypi/bin/ai-paladin --help
/tmp/ai-paladin-testpypi/bin/ai-paladin-hook --status
```

`--version` should print `ai-paladin 0.3.0`. `--help` should exit 0.
`ai-paladin-hook --status` should exit 0 (it may say the hook is not
installed, which is expected in a clean venv).

TestPyPI will not accept a second upload of version 0.3.0. If a redo
is needed, do not change the committed `VERSION` file (it must stay
`X.Y.Z`, and the VS Code extension must match it). Re-dispatch with
`-f prerelease=rc1` to upload `0.3.0rc1` instead. Details are in
`docs/RELEASING.md`.

A later production PyPI release uses the same workflow on a `v0.3.0`
tag, after the `pypi` Trusted Publisher is registered, and waits for
Rob's approval on the `pypi` environment. That is not this step.

### (c) Merge `feature/distribution-init` into `sanctuary`

After the TestPyPI dry run looks good, Rob opens (or accepts) a PR
from the distribution work into `sanctuary` and merges it himself,
using the bypass checkbox if the ruleset requires it. Bots do not
merge, and they must not open that PR until the dry run is done.

See the PR #4 note in Current state: #4 already uses this head and
base and is do-not-merge. Leave it alone. The merge PR will need a
new branch, or Rob's decision on #4.

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

As of 2026-11-28, on `feature/testpypi-release`, that
suite is **183 passed, 2 skipped** (185 tests run). The skips are:

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
