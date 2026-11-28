# Configuration manual changes

What changed between versions of the configuration manual. The newest
manual lives in `latest/`. Frozen folders are not edited.

## latest (v0.3.0)

The HTML that was current after PRs #7, #8 and #9, with cover and
version labels updated from v0.1.0 to v0.3.0.

- Paths say `ai-paladin/` instead of `ai-org-router/` (PR #7).
- Hook write-scope and credential wording covers shell and script
  writes, and the opt-in `hook.yaml` settings
  `shell_writes_enforce_allow` and `scripts_may_read_env_files`
  (PR #8).
- Uninstall is documented as `ai-paladin uninstall` first (it asks
  "Do you want me to remove the hooks I added outside of python?(Y/n)"
  and removes only hook entries it recorded), then
  `pip uninstall ai-paladin`. It does not run pip itself (PR #9).
- The PDF build script lives at
  `ai-paladin/HUMAN_C_SUITE_DOCUMENTATION/build_pdfs.sh`.
- The files in `latest/` are named `USER_CONFIG_MANUAL.html` and
  `USER_CONFIG_MANUAL.pdf` (renamed from `USER_CONFIG_DECK`). Frozen
  `v0.2/` still uses the older `USER_CONFIG_DECK` filenames.

The v0.3.0 PDF was built on 2026-11-28 (16 pages, A4 landscape) and
lives at `latest/USER_CONFIG_MANUAL.pdf`.

## v0.2

Frozen. Do not edit.

The PDF last built on 2026-11-24, and the HTML it was built from
(commit `cbc9355`, "Safe uninstall: hook removed everywhere before the
package"). That HTML still describes the earlier uninstaller, which ran
pip itself, and its cover still reads v0.1.0: that was the label when
the PDF was built.
