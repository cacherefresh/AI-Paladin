"""
AGENTS.md, CLAUDE.md and HANDOFF.md live at the repo root so tools can
read them, and must not be shipped in the pip package.

Run from ai-paladin/:  python3 -m unittest tests.test_repo_only_docs -v
"""

import re
import sys
import unittest
from pathlib import Path

_AI_PALADIN = Path(__file__).resolve().parents[1]
_REPO = _AI_PALADIN.parent
sys.path.insert(0, str(_AI_PALADIN))

REPO_ONLY = ("AGENTS.md", "CLAUDE.md", "HANDOFF.md")


class RepoOnlyDocsTest(unittest.TestCase):

    def test_files_exist_at_repo_root(self):
        for name in REPO_ONLY:
            path = _REPO / name
            self.assertTrue(path.is_file(), f"missing repo-root {name}")
            self.assertGreater(path.stat().st_size, 0, f"{name} is empty")

    def test_claude_md_points_at_agents_md(self):
        text = (_REPO / "CLAUDE.md").read_text(encoding="utf-8")
        self.assertIn("AGENTS.md", text)

    def test_agents_md_names_both_tools_and_the_handoff(self):
        text = (_REPO / "AGENTS.md").read_text(encoding="utf-8")
        self.assertIn("## Who works on this repo", text)
        self.assertIn("Claude Code", text)
        self.assertIn("Grok Bot", text)
        self.assertIn("ai-paladin-lead-engineer-bot", text)
        self.assertIn("HANDOFF.md", text)

    def test_pyproject_does_not_ship_them(self):
        text = (_REPO / "pyproject.toml").read_text(encoding="utf-8")
        for name in REPO_ONLY:
            self.assertNotIn(name, text, f"{name} is referenced in pyproject.toml")
        # Wheel package data is only the listed globs under ai-paladin/.
        self.assertIn("include-package-data = false", text)
        self.assertIn('"" = "ai-paladin"', text)

    def test_manifest_does_not_include_them(self):
        manifest = _REPO / "MANIFEST.in"
        if not manifest.is_file():
            return
        # A bare include/graft would pull them into the sdist. An
        # explicit "exclude AGENTS.md" line is allowed.
        text = manifest.read_text(encoding="utf-8")
        include = re.compile(
            r"^\s*(include|recursive-include|graft)\b.*$",
            re.IGNORECASE | re.MULTILINE,
        )
        for match in include.finditer(text):
            chunk = match.group(0)
            for name in REPO_ONLY:
                if name in chunk:
                    self.fail(f"MANIFEST.in would include {name}: {chunk.strip()}")


if __name__ == "__main__":
    unittest.main()
