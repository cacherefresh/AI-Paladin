# Distribution checklist

Tick a box (`[x]`) when a step is done and add the date. **(Rob)** marks steps
only you can do: account signups, uploads, pushes. Everything else can be
prepared in the repository and committed for you to review.

Nothing here is ever published or pushed by an agent. Every upload and every
`git push` is yours.

## 0. Identity and licence

- [x] Package name chosen: `ai-paladin` (2026-11-22)
- [x] Publisher / organisation ID chosen: `cacherefresh` (2026-11-22)
- [x] Brand display form ℂacheℝefresh, with ASCII fallback rule in `AGENTS.md` (2026-11-22)
- [x] Licence: modified Apache 2.0 in `LICENSE`, plus `NOTICE` (2026-11-16)
- [x] Checked PyPI: `ai-paladin` and `cacherefresh` free, `paladin` taken by someone else (2026-11-16)

## 1. Code changes needed before any package

- [x] Move `router`, `server`, `security`, `bus`, `nodes`, `bigai` under one `ai_paladin/` package; gate YAML stays in place (2026-11-22)
- [x] Move the VS Code extension to `vscode/ai-paladin/` (2026-11-22)
- [x] Move logs and writable settings out of the code folder: `~/.local/state/ai-paladin/logs/` and `~/.config/ai-paladin/`; the demo keeps them in the repo (2026-11-24)
- [x] User overrides: `keywords.yaml` overlay (add, or remove by name, reported as WEAKENED); `policy.yaml` / `roster.yaml` / `catalog.yaml` replaced whole (2026-11-24)
- [x] Shipped keyword defaults cut to a small generic set; demo terms moved to the demo overlay `config/keywords.yaml` (2026-11-24)
- [x] `ai-paladin` command (`--demo`, `--where`, `--port`), also `python3 -m ai_paladin`; works from an editable install (2026-11-24)
- [x] Tests: 36 pass, including 13 for the overlay rules (2026-11-24)
- [x] `security/policies/` and `security/monitors/` enforced: router (allowlist, credential files, fence-probing) and Claude Code hook `ai-paladin-hook` with `--install` / `--uninstall` (2026-11-24)
- [x] Uninstall order is told everywhere a user can meet it (2026-11-24):
      root README "Uninstalling" (also the PyPI page), the VS Code extension's README, `ai-paladin-hook --install` output, hooks/README.md, and the user manual (page 15)
- [x] A leftover hook entry explains itself: if AI-Paladin was removed first, Claude Code's refusal names the settings file to fix and the `--uninstall` command (2026-11-24)
- [x] `ai-paladin uninstall`: removes the hook from every recorded install (registry kept by `--install`), stops if any cannot be removed, then runs pip (or pipx) uninstall and ends with an all-caps banner. pip itself cannot run code at uninstall time (2026-11-24)
- [x] Tests pass after the move (23/23), and the router boots, passes its egress self-test and pins protected prompts on-prem (2026-11-22)
- [ ] **(Rob)** Full `./run_demo.sh` with Ollama, to confirm the demo end to end

## 2. VS Code Marketplace

- [x] `package.json`: name `ai-paladin`, publisher `cacherefresh`, display name "ℂacheℝefresh's AI-Paladin", licence `Apache-2.0` (2026-11-22)
- [ ] Add `repository`, `homepage` and `bugs` links to `package.json`
- [ ] Add an icon (128×128 PNG) and point `package.json` at it
- [ ] Put a copy of `LICENSE` inside `vscode/ai-paladin/` - the packaging tool looks for it there
- [ ] Build locally with `npx @vscode/vsce package` and install the `.vsix` by hand to test it
- [ ] **(Rob)** Create a Microsoft account / Azure DevOps organisation if you do not have one
- [ ] **(Rob)** Register publisher ID `cacherefresh` at https://marketplace.visualstudio.com/manage - put **ℂacheℝefresh** in the display-name field
- [ ] **(Rob)** Create a Personal Access Token scoped to Marketplace → Manage only, with a short expiry
- [ ] **(Rob)** First publish: `npx @vscode/vsce publish`
- [ ] **(Rob)** Optional: verify `cacherefresh.com` as the publisher's domain, which puts a verified badge on the listing

## 3. PyPI

- [x] Minimal `pyproject.toml` at the repo root: name, licence, PyYAML, the `ai-paladin` command; editable install tested (2026-11-24)
- [ ] Ship the defaults inside the package (router/*.yaml, agents/, models/, ui/, demo/) so a wheel works, not just an editable install
- [ ] Build locally (`python3 -m build`) and install the wheel into a clean virtual environment to test it
- [ ] Add a GitHub Actions release workflow using Trusted Publishing - no stored upload key
- [ ] **(Rob)** Create a PyPI account with two-factor authentication
- [ ] **(Rob)** Create the PyPI organisation `cacherefresh`
- [ ] **(Rob)** Register the Trusted Publisher on PyPI: repository `cacherefresh/AI-Paladin`, the release workflow's file name
- [ ] **(Rob)** Optional dry run on TestPyPI first
- [ ] **(Rob)** Tag and push the first release, which publishes `ai-paladin` 0.1.0 and claims the name

PyPI only lets you claim a name with a real, working release. An empty
placeholder can be taken back under its name-squatting policy.

## 4. GitHub Releases (signed files for offline installs)

- [ ] Release workflow attaches the wheel, the `.vsix` and a `SHA256SUMS` file to each release
- [ ] Sign each release (Sigstore, through the same workflow - no key to manage)
- [ ] Document how to verify a download, in `DISTRIBUTION/README.md`
- [ ] **(Rob)** Push the first release tag

## 5. Ubuntu (Launchpad PPA)

Users will install with:

```bash
sudo add-apt-repository ppa:cacherefresh/ai-paladin
sudo apt install ai-paladin
systemctl --user enable --now ai-paladin    # start now and at every login
```

### Decisions

- [x] Channel: a PPA on Launchpad, `ppa:cacherefresh/ai-paladin` (2026-11-22)
- [x] Runs as: a per-user systemd service, installed but **not** switched on until the user enables it (2026-11-22)
- [x] Ubuntu 24.04 LTS (noble) only, Python 3.12 (2026-11-22)
- [x] Ollama: documented, never installed or downloaded by the package (2026-11-22)

### Launchpad setup (Rob)

- [ ] **(Rob)** Create a Launchpad account
- [ ] **(Rob)** Sign the Ubuntu Code of Conduct on Launchpad (required before uploading to a PPA)
- [ ] **(Rob)** Create an OpenPGP signing key and upload its public part to Launchpad - Launchpad only accepts uploads signed by it
- [ ] **(Rob)** Create a Launchpad team named `cacherefresh`, display name ℂacheℝefresh, so the PPA address is `ppa:cacherefresh/ai-paladin`
- [ ] **(Rob)** Create the PPA `ai-paladin` under that team

### Packaging (prepared in the repo for review)

Needs section 1 (code changes) and section 3's `pyproject.toml` done first.

- [ ] `debian/` folder: `control`, `rules`, `changelog`, `copyright`, `source/format`
- [ ] `control`: depends on `python3-yaml` from Ubuntu's own archive, so nothing is fetched from PyPI. Ollama is not listed, because it is not in Ubuntu's archive
- [ ] `copyright` in Debian's machine-readable format: Apache-2.0, with the preamble noted as non-binding
- [ ] `ai-paladin.service` user unit, installed to `/usr/lib/systemd/user/` and not enabled by default. Two users on one machine would otherwise both start a router on port 8722
- [ ] Shipped default config under `/usr/share/ai-paladin/`; each user's overrides in `~/.config/ai-paladin/`; logs in `~/.local/state/ai-paladin/`
- [ ] After install, print the Ollama install link and the `systemctl --user enable --now ai-paladin` line
- [ ] `prerm` prints: "run `ai-paladin-hook --uninstall --all` as each user who installed the hook first". It runs as root, so it must only warn - never edit users' Claude Code settings
- [ ] Build the source package (`debuild -S`) and test-build it for noble in a clean environment (`sbuild`)
- [ ] `lintian` reports no errors
- [ ] Install the built package in a fresh Ubuntu 24.04 container or VM, enable the service, and open the console

### First upload (Rob)

- [ ] **(Rob)** `dput ppa:cacherefresh/ai-paladin ai-paladin_<version>_source.changes`
- [ ] **(Rob)** Wait for Launchpad's build to succeed, then install from the PPA on a clean machine
- [ ] Mark Ubuntu as **Live** in `DISTRIBUTION/README.md`

Launchpad builds the package from source on its own servers, with no internet
access during the build. That gives buyers a public record that the package
matches the source.

**Later, not planned yet:** Ubuntu 26.04 LTS once it is widely used; the
official Ubuntu archive, which needs a Debian sponsor.
