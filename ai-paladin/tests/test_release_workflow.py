"""
The pip release workflow uses Trusted Publishing (OIDC), never a
stored token. docs/RELEASING.md is the runbook Rob follows, and it
lives outside the pip package.

Run from ai-paladin/:  python3 -m unittest tests.test_release_workflow -v
"""

import re
import sys
import unittest
from pathlib import Path

_AI_PALADIN = Path(__file__).resolve().parents[1]
_REPO = _AI_PALADIN.parent
sys.path.insert(0, str(_AI_PALADIN))

WORKFLOW = _REPO / ".github" / "workflows" / "release.yml"
RELEASING = _REPO / "docs" / "RELEASING.md"
PYPROJECT = _REPO / "pyproject.toml"


class ReleaseWorkflowTest(unittest.TestCase):

    def setUp(self):
        self.assertTrue(WORKFLOW.is_file(), "missing .github/workflows/release.yml")
        self.wf = WORKFLOW.read_text(encoding="utf-8")

    def test_trigger_is_dispatch_to_testpypi_and_tags_to_pypi(self):
        self.assertIn("workflow_dispatch:", self.wf)
        self.assertIn("testpypi", self.wf)
        self.assertRegex(self.wf, r'tags:\n\s+-\s+"v\*"')
        # Production PyPI is not a dispatch option.
        # The target choice lists only testpypi; pypi is tag-only.
        self.assertIn("inputs:", self.wf)
        self.assertIn("Publish to PyPI", self.wf)
        self.assertIn("Publish to TestPyPI", self.wf)
        self.assertIn("startsWith(github.ref, 'refs/tags/v')", self.wf)

    def test_uses_oidc_trusted_publishing_not_a_token(self):
        self.assertIn("id-token: write", self.wf)
        self.assertIn("pypa/gh-action-pypi-publish", self.wf)
        self.assertIn("repository-url: https://test.pypi.org/legacy/", self.wf)
        lowered = self.wf.lower()
        for needle in (
            "password:",
            "twine_password",
            "pypi_api_token",
            "${{ secrets",
            "pypi_token",
            "testpypi_token",
        ):
            self.assertNotIn(needle, lowered, f"workflow must not use {needle}")

    def test_environment_names(self):
        self.assertIn("name: testpypi", self.wf)
        self.assertIn("name: pypi", self.wf)
        self.assertIn("https://test.pypi.org/project/ai-paladin/", self.wf)
        self.assertIn("https://pypi.org/project/ai-paladin/", self.wf)

    def test_build_checks_version_against_tag_and_artifacts(self):
        self.assertIn("twine check --strict", self.wf)
        self.assertIn("python -m build", self.wf)
        # Tag v0.3.0 must match VERSION 0.3.0.
        self.assertIn("does not match VERSION", self.wf)
        self.assertIn('expected = "v" + base', self.wf)
        self.assertIn("AGENTS.md", self.wf)
        self.assertIn("prerelease", self.wf)

    def test_testpypi_job_is_limited_to_known_branches(self):
        self.assertIn("refs/heads/sanctuary", self.wf)
        self.assertIn("refs/heads/development", self.wf)
        self.assertNotIn("refs/heads/DEVELOPMENT", self.wf)
        self.assertNotIn("refs/heads/feature/distribution-init", self.wf)


class ReleasingDocsTest(unittest.TestCase):

    def setUp(self):
        self.assertTrue(RELEASING.is_file(), "missing docs/RELEASING.md")
        self.text = RELEASING.read_text(encoding="utf-8")

    def test_runbook_has_the_exact_publisher_fields(self):
        for needle in (
            "cacherefresh",
            "AI-Paladin",
            "release.yml",
            "testpypi",
            "https://test.pypi.org/manage/account/publishing/",
            "ai-paladin==0.3.0",
            "https://test.pypi.org/simple/",
            "--extra-index-url https://pypi.org/simple/",
            "ai-paladin --version",
            "ai-paladin-hook --status",
        ):
            self.assertIn(needle, self.text, f"missing {needle!r} in docs/RELEASING.md")

    def test_runbook_explains_version_vs_prerelease_redos(self):
        self.assertIn("0.3.0rc1", self.text)
        self.assertIn("0.3.0.dev1", self.text)
        self.assertIn("Do **not** change the committed `VERSION` file", self.text)
        self.assertIn("X.Y.Z", self.text)
        self.assertIn("test_version.py", self.text)

    def test_runbook_explains_how_to_start_a_dispatch(self):
        self.assertIn("default branch", self.text)
        self.assertIn("Actions tab", self.text)
        self.assertIn("prerelease=rc1", self.text)
        self.assertIn("development", self.text)
        self.assertNotIn("DEVELOPMENT", self.text)
        self.assertNotIn("feature/distribution-init", self.text)


class PackagingMetadataTest(unittest.TestCase):

    def test_pyproject_uses_spdx_license_and_current_setuptools(self):
        text = PYPROJECT.read_text(encoding="utf-8")
        self.assertIn('requires = ["setuptools>=77"]', text)
        self.assertIn('license = "Apache-2.0"', text)
        self.assertIn('license-files = ["LICENSE", "NOTICE"]', text)
        self.assertNotIn("License :: OSI Approved :: Apache Software License", text)
        self.assertNotIn("license = {text", text)
        self.assertIn("Programming Language :: Python :: 3.13", text)
        self.assertIn("Issues = ", text)
        self.assertIn("Changelog = ", text)


if __name__ == "__main__":
    unittest.main()
