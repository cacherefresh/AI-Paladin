# Distribution

Where AI-Paladin is published, under what names, and how a user can check that
what they installed is really ours. The step-by-step work, with what is done
and what is not, is in [CHECKLIST.md](CHECKLIST.md).

**Nothing is published yet.** Every channel below is planned. Until one is
marked live here, the only official source is the GitHub repository.

## Names

| | Value |
|---|---|
| Package name | `ai-paladin` |
| Publisher / organisation ID | `cacherefresh` |
| Publisher display name | ℂacheℝefresh |
| VS Code display name | ℂacheℝefresh's AI-Paladin |
| Licence | Modified Apache License 2.0 - Apache 2.0 terms unaltered, plus a non-binding preamble. See [LICENSE](../LICENSE). |

Registries accept only ASCII in names, so the identifiers are always
`cacherefresh` and `ai-paladin`, never the double-struck letters. The full
naming rule is in [AGENTS.md](../AGENTS.md).

**Any package called `paladin`, `ai_paladin_official`, `aipaladin` or similar
that does not come from the `cacherefresh` publisher is not ours.** On PyPI,
`paladin` already belongs to an unrelated project.

## Channels

| Channel | What ships | Install | Status |
|---|---|---|---|
| **GitHub** | Source | `git clone https://github.com/cacherefresh/AI-Paladin` | Live |
| **GitHub Releases** | Signed wheel (`.whl`), `.vsix` and checksums | Download, verify, then install the file | Planned |
| **PyPI** | The router as a Python package | `pip install ai-paladin` | Planned - name not yet claimed |
| **VS Code Marketplace** | The status-bar extension | Search "ai-paladin" or "cacherefresh" | Planned - publisher not yet registered |
| **Ubuntu 24.04** | `.deb` from a Launchpad PPA | `add-apt-repository ppa:cacherefresh/ai-paladin`, then `apt install ai-paladin` | Planned |

### Two pieces, not one

- **The router** (`ai-paladin/`) is the product: the gates, the egress
  guard, the console. It ships through PyPI, GitHub Releases and, later, Ubuntu.
- **The VS Code extension** (`vscode/ai-paladin/`) is a read-only
  window onto a running router. Installed alone it shows `⊘ AI-Paladin`
  (router not running) in the status bar and does nothing else. It ships through
  the Marketplace and as a `.vsix` on GitHub Releases.

## Why both a registry and signed files

A registry (`pip install`, the Marketplace) is convenient and works for most
people. A security buyer may not want to trust a registry at all, and an
air-gapped site cannot reach one. For them, each release is also attached to
GitHub Releases as files with a checksum and a signature: download on a
connected machine, verify, carry across, install from the file.

```bash
# Offline install, once the signed wheel exists
sha256sum -c ai_paladin-<version>-py3-none-any.whl.sha256
pip install ./ai_paladin-<version>-py3-none-any.whl
```

PyPI uploads will use **Trusted Publishing**: GitHub Actions authenticates
with a short-lived token for each release, so no long-lived upload key exists
to be stolen. The workflow is `.github/workflows/release.yml`. The steps
to run a TestPyPI dry run, and later a production release, are in
[docs/RELEASING.md](../docs/RELEASING.md).

## Dependencies

One Python dependency: **PyYAML**. Everything else is the Python standard
library. Every extra dependency is something else a user has to trust, so
adding another needs a stated reason.

[Ollama](https://ollama.com) is required to run a local model but is **not**
bundled or installed by any AI-Paladin package. It is a separate program that
can download models from the internet, and AI-Paladin never downloads models
itself. See `ai-paladin/docs/ROADMAP.md`, section 8.

## What must change in the code before any package

These are blockers for PyPI and Ubuntu alike. They are tracked in the checklist.

1. ~~**Generic top-level module names.**~~ **Done 2026-11-22.** The code now
   lives under one `ai_paladin/` package (`ai-paladin/ai_paladin/`). Users
   install and run `ai-paladin`; only Python imports use the underscore,
   because Python import names cannot contain a hyphen. The gate files stayed
   where they were (`router/`, `security/policies/`, `security/monitors/`).
2. ~~**Writable state inside the code folder.**~~ **Done 2026-11-24.** Logs
   go to `~/.local/state/ai-paladin/logs/` and settings to
   `~/.config/ai-paladin/`; the demo keeps both inside the repo.
3. ~~**How users override the shipped config.**~~ **Done 2026-11-24.**
   `keywords.yaml` is an overlay (add or remove by name; removals reported as
   WEAKENED); `policy.yaml`, `roster.yaml` and `catalog.yaml` are replaced
   whole by a user copy. See the root README, "Where settings live".
4. ~~**The shipped defaults sit beside the code, not inside the
   package.**~~ **Done 2026-11-27.** The wheel carries them as package data
   under `ai_paladin/_shipped/`; the repository keeps them where they are.
   `ai-paladin/tests/wheel_smoke.py` builds the wheel, installs it into a
   clean virtual environment and boots the router from it.

## Ubuntu

Planned for **Ubuntu 24.04 LTS** through a Launchpad PPA,
`ppa:cacherefresh/ai-paladin`. Updates then arrive with a normal
`apt upgrade`.

- **Built by Ubuntu's servers, from source.** Launchpad builds the package
  itself, with no internet access during the build, so anyone can see that
  the package came from the published source.
- **Per-user service, off until you switch it on.** The package installs a
  systemd user service but does not start it. `systemctl --user enable --now
  ai-paladin` starts it now and at every login. The router stays single-user
  and listens on `127.0.0.1` only, as it does today.
- **Dependencies come from Ubuntu.** PyYAML is installed as Ubuntu's
  `python3-yaml`, so nothing is fetched from PyPI.
- **Ollama is not installed.** It is not in Ubuntu's archive, and a package
  that downloads a third-party installer would undercut the containment
  promise. The package prints the official install link instead.
- **Files:** shipped defaults in `/usr/share/ai-paladin/`, your overrides in
  `~/.config/ai-paladin/`, logs in `~/.local/state/ai-paladin/`.

The Ubuntu package version must match the repo-root `VERSION` file, the same number pip and the VS Code extension use. When Debian packaging is added, the first entry in `debian/changelog` (or `packaging/debian/changelog`, `DISTRIBUTION/debian/changelog`, `ubuntu/debian/changelog`) is the source the test reads. `ai-paladin/tests/test_version.py` fails if they drift. There is no Ubuntu packaging in the tree yet.

Steps are in [CHECKLIST.md](CHECKLIST.md#5-ubuntu-launchpad-ppa).
