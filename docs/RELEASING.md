# Releasing the pip package

How ℂacheℝefresh publishes `ai-paladin` to TestPyPI and PyPI.

Agents do not upload, do not create accounts, and do not store or
handle a PyPI API token. Only Rob publishes. The workflow uses
[Trusted Publishing](https://docs.pypi.org/trusted-publishers/)
(OIDC): GitHub Actions gets a short-lived token for each run, so no
long-lived upload key exists in the repository or in GitHub secrets.

The workflow file is `.github/workflows/release.yml`. It must exist
on the branch you run it from. For the first TestPyPI dry run, merge
the PR that adds this file into `feature/distribution-init`, then
dispatch from that branch. Do not merge `feature/distribution-init`
into `sanctuary` until the dry run looks good.

## One-time setup (Rob)

Do these once, before the first upload. A TestPyPI account is not a
PyPI account; create both if you will later publish to production.

### 1. Create a TestPyPI account and turn on 2FA

1. Register at https://test.pypi.org/account/register/
2. Confirm the email and sign in.
3. Enable two-factor authentication under
   https://test.pypi.org/manage/account/. Publishing requires 2FA.

You do not need an API token. The workflow authenticates with
Trusted Publishing, not a stored token.

### 2. Create the GitHub environments

In the repository: Settings → Environments → New environment.
The names must match the workflow and the Trusted Publisher exactly.

1. Create `testpypi`. No required reviewer is needed (the dry run
   should run once you dispatch it). Optional: limit deployment
   branches to `feature/distribution-init`, `sanctuary`, and later
   `DEVELOPMENT`.
2. Create `pypi`. Under "Required reviewers", add yourself
   (`cacherefresh`, or your GitHub user). This is the approval gate
   for a production upload. Optional: limit this environment to tags
   matching `v*`.

The `pypi` environment is used only when a `v*` tag is pushed. Do
not skip the required reviewer.

### 3. Register a pending Trusted Publisher on TestPyPI

Until the first successful upload, the project does not exist on
TestPyPI. Add a pending publisher, which will create
`ai-paladin` on the first run:

1. Open https://test.pypi.org/manage/account/publishing/
2. Fill in:

   | Field | Value |
   |---|---|
   | PyPI project name | `ai-paladin` |
   | Owner | `cacherefresh` |
   | Repository | `AI-Paladin` |
   | Workflow name | `release.yml` |
   | Environment name | `testpypi` |

3. Leave the branch field blank. The workflow itself only publishes
   to TestPyPI from `feature/distribution-init`, `sanctuary`, or
   `DEVELOPMENT`.
4. Submit the pending publisher.

Use those values exactly, including the workflow filename
`release.yml` (not `Release` and not a path).

### 4. Later, for production PyPI (not this dry run)

After the TestPyPI dry run looks good, and after distribution has
merged into `sanctuary`:

1. Create a PyPI account at https://pypi.org with 2FA
   (https://pypi.org/manage/account/). This is separate from TestPyPI.
2. Optional, but planned: create the PyPI organization `cacherefresh`.
3. Add a pending Trusted Publisher at
   https://pypi.org/manage/account/publishing/ with the same fields
   as above, except Environment name is `pypi`.
4. Production publishes only from a `v*` tag, and waits for your
   approval on the `pypi` GitHub environment.

## Running the TestPyPI dry run

After `.github/workflows/release.yml` is on
`feature/distribution-init`:

GitHub only lists `workflow_dispatch` workflows in the Actions tab
when the file also exists on the default branch (`sanctuary`). Until
then, start the run from your machine with `gh`:

```bash
gh workflow run release.yml \
  --repo cacherefresh/AI-Paladin \
  --ref feature/distribution-init \
  -f target=testpypi
```

Then watch it under the Actions tab, or with
`gh run watch --repo cacherefresh/AI-Paladin`.

The first run will fail if the `testpypi` environment is missing or
the pending publisher does not match (wrong workflow filename,
environment name, owner, or repository). The job log usually says
which.

Do not run this workflow from `feature/testpypi-release` or another
feature branch: the TestPyPI job is limited to
`feature/distribution-init`, `sanctuary`, and `DEVELOPMENT`.

### Verify the install

In a clean virtual environment, install the uploaded package. PyYAML
is pulled from the real PyPI index because it may not be on TestPyPI:

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

`--version` should print `ai-paladin 0.3.0`. `--help` should print
the command usage and exit 0. `ai-paladin-hook --status` should run
and exit 0 (it may say the hook is not installed, which is expected
in a clean venv).

Optional further checks:

```bash
/tmp/ai-paladin-testpypi/bin/ai-paladin --where
/tmp/ai-paladin-testpypi/bin/ai-paladin uninstall --dry-run
```

`--where` lists the shipped files. `uninstall --dry-run` must not
change anything (it may say there is nothing recorded).

The project page will be
https://test.pypi.org/project/ai-paladin/0.3.0/

## If you need to redo the TestPyPI upload

TestPyPI and PyPI both refuse a second upload of the same version,
even if you delete the files. The version string stays reserved.

Do **not** change the committed `VERSION` file to `0.3.0rc1` or
`0.3.0.dev1` in order to retry. `VERSION` must stay a single `X.Y.Z`
line. `ai-paladin/tests/test_version.py` fails otherwise, and the
VS Code extension (`vscode/ai-paladin/package.json`) and, when it
exists, Ubuntu packaging must match that file. A VERSION bump is a
new software release, not a TestPyPI retry.

Instead, re-dispatch the workflow with the `prerelease` input. That
changes the version only in the runner, for that build:

| `prerelease` input | Package version uploaded |
|---|---|
| (empty) | `0.3.0` (the VERSION file) |
| `rc1` | `0.3.0rc1` |
| `dev1` or `.dev1` | `0.3.0.dev1` |

```bash
gh workflow run release.yml \
  --repo cacherefresh/AI-Paladin \
  --ref feature/distribution-init \
  -f target=testpypi \
  -f prerelease=rc1
```

Then install that pre-release:

```bash
/tmp/ai-paladin-testpypi/bin/pip install \
  -i https://test.pypi.org/simple/ \
  --extra-index-url https://pypi.org/simple/ \
  ai-paladin==0.3.0rc1
```

The production 0.3.0 upload to real PyPI still uses the committed
`VERSION` file and a `v0.3.0` tag. Do not pass `prerelease` on a
tag; the workflow rejects that.

## Production PyPI (after the dry run)

1. Finish the one-time PyPI publisher and `pypi` environment steps
   above.
2. Merge the distribution work into `sanctuary` (see `HANDOFF.md`
   step (c) about PR #4).
3. From `sanctuary`, when `VERSION` is `0.3.0`:

   ```bash
   git switch sanctuary
   git pull
   git tag v0.3.0
   git push origin v0.3.0
   ```

4. The Release workflow builds the artifacts, checks that the tag
   equals `v` plus the VERSION file, and starts the `publish-pypi`
   job. That job waits on the `pypi` environment until you approve
   it in the Actions UI.
5. Confirm with:

   ```bash
   python3 -m venv /tmp/ai-paladin-pypi
   /tmp/ai-paladin-pypi/bin/pip install ai-paladin==0.3.0
   /tmp/ai-paladin-pypi/bin/ai-paladin --version
   ```

Do not force-push a tag to reuse a version that already reached
PyPI. If 0.3.0 is published, the next upload is a new VERSION.

## Local build (optional, no upload)

To inspect the artifacts on your machine without publishing:

```bash
python3 -m pip install build twine
python3 -m build
python3 -m twine check --strict dist/*
```

The wheel and sdist version must be `0.3.0`. `AGENTS.md`,
`CLAUDE.md`, `HANDOFF.md`, and the pitch-deck / manual tree under
`HUMAN_C_SUITE_DOCUMENTATION/` must not appear in either artifact.
