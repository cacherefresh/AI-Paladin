"""
The repo-root VERSION file is the single source for the project version.
pip (pyproject.toml and ai_paladin.__version__), the VS Code extension
(package.json) and, when it exists, Ubuntu/Debian packaging must match it.

Run from ai-paladin/:  python3 -m unittest tests.test_version -v
"""

import json
import re
import sys
import unittest
from pathlib import Path

_AI_PALADIN = Path(__file__).resolve().parents[1]
_REPO = _AI_PALADIN.parent
sys.path.insert(0, str(_AI_PALADIN))

from ai_paladin import __version__                                  # noqa: E402

VERSION_RE = re.compile(r"^\d+\.\d+\.\d+$")

# debian/changelog lives at one of these paths once Ubuntu packaging exists.
DEBIAN_CHANGELOGS = (
    "debian/changelog",
    "packaging/debian/changelog",
    "DISTRIBUTION/debian/changelog",
    "ubuntu/debian/changelog",
)


def _version_file() -> Path:
    return _REPO / "VERSION"


def _read_version() -> str:
    text = _version_file().read_text(encoding="utf-8")
    lines = [ln.strip() for ln in text.splitlines() if ln.strip() and not ln.strip().startswith("#")]
    if not lines:
        raise AssertionError("VERSION is empty")
    return lines[0]


class VersionAgreementTest(unittest.TestCase):

    def test_version_file_exists_and_is_simple(self):
        self.assertTrue(_version_file().is_file(), "missing repo-root VERSION file")
        ver = _read_version()
        self.assertRegex(ver, VERSION_RE, "VERSION must be a single X.Y.Z line")

    def test_pyproject_reads_version_file(self):
        text = (_REPO / "pyproject.toml").read_text(encoding="utf-8")
        self.assertIn('version = {file = "VERSION"}', text)
        # A static project version would drift from VERSION.
        self.assertNotRegex(
            text,
            r'(?m)^version\s*=\s*"[0-9]',
            "pyproject.toml must not hard-code a project version",
        )

    def test_package_dunder_version_matches(self):
        self.assertEqual(__version__, _read_version())

    def test_vscode_package_json_matches(self):
        path = _REPO / "vscode" / "ai-paladin" / "package.json"
        self.assertTrue(path.is_file(), "missing vscode/ai-paladin/package.json")
        data = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual(data["version"], _read_version())

    def test_debian_changelog_matches_when_present(self):
        found = [p for p in DEBIAN_CHANGELOGS if (_REPO / p).is_file()]
        if not found:
            self.skipTest("no Ubuntu/Debian changelog in the tree yet")
        wanted = _read_version()
        # First entry: "ai-paladin (0.3.0-1) ..."
        pat = re.compile(r"^\S+\s+\(([^)]+)\)")
        for rel in found:
            first = (_REPO / rel).read_text(encoding="utf-8").lstrip().splitlines()[0]
            m = pat.match(first)
            self.assertIsNotNone(m, f"{rel} does not look like a debian/changelog: {first!r}")
            deb_ver = m.group(1)
            upstream = deb_ver.split("-", 1)[0]
            self.assertEqual(
                upstream, wanted,
                f"{rel} upstream version {upstream!r} does not match VERSION {wanted!r}",
            )


if __name__ == "__main__":
    unittest.main()
